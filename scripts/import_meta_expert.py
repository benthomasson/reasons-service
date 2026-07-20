#!/usr/bin/env python3
"""Import a meta-expert repo (with cluster subdirectories) into reasons-service.

A meta-expert has N cluster subdirectories, each with its own sources/, entries/,
and beliefs.md. This script walks all clusters and imports everything into a
single domain, prefixing source slugs with the cluster name to avoid collisions.

Usage:
    python scripts/import_meta_expert.py ~/git/redhat-expert --name redhat-expert --domain "Red Hat"
    python scripts/import_meta_expert.py ~/git/redhat-expert --name redhat-expert --domain "Red Hat" --domain-id UUID
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
TOKEN_PATH = Path.home() / ".config" / "expert" / "token.json"

# Directories that are not clusters
SKIP_DIRS = {
    "entries", "sources", "evals", "scripts", "reviews",
    "dataverse-schemas", ".git", "__pycache__", "rag.chromadb",
}


def discover_clusters(repo: Path) -> list[str]:
    """Find cluster subdirectories that have sources/ or beliefs.md."""
    clusters = []
    for d in sorted(repo.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name in SKIP_DIRS:
            continue
        if (d / "sources").is_dir() or (d / "beliefs.md").is_file():
            clusters.append(d.name)
    return clusters


def parse_beliefs(beliefs_path: Path) -> list[dict]:
    """Parse beliefs.md into a list of claim dicts."""
    text = beliefs_path.read_text()
    claims = []

    pattern = re.compile(
        r"^### (\S+) \[(IN|OUT|STALE)\][^\n]*\n"
        r"(.*?)"
        r"(?=^### |\Z)",
        re.MULTILINE | re.DOTALL,
    )

    for match in pattern.finditer(text):
        claim_id = match.group(1)
        status = match.group(2)
        body = match.group(3).strip()

        lines = body.split("\n")
        claim_text_lines = []
        source = None
        source_hash = None

        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith("- Source:") and "hash" not in line_stripped.lower():
                source = line_stripped.replace("- Source:", "").strip()
            elif line_stripped.startswith("- Source hash:"):
                source_hash = line_stripped.replace("- Source hash:", "").strip()
            elif line_stripped and not line_stripped.startswith("- "):
                claim_text_lines.append(line_stripped)

        claim_text = " ".join(claim_text_lines)
        if not claim_text:
            continue

        claims.append({
            "id": claim_id,
            "text": claim_text,
            "status": status,
            "source": source,
            "source_hash": source_hash,
        })

    return claims


def find_sources(sources_dir: Path, cluster: str) -> list[dict]:
    """Find source markdown files, prefixing slugs with cluster name."""
    sources = []

    for md_file in sorted(sources_dir.rglob("*.md")):
        content = md_file.read_text()
        slug = f"{cluster}/{md_file.stem}"

        # Extract URL from YAML frontmatter (supports both source: and source_url:)
        url = None
        fm_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if fm_match:
            for line in fm_match.group(1).split("\n"):
                if line.startswith("source_url:"):
                    url = line.replace("source_url:", "").strip()
                elif line.startswith("source:") and not line.startswith("source_id:"):
                    url = line.replace("source:", "").strip()

        # Count words (excluding frontmatter)
        body = content
        if fm_match:
            body = content[fm_match.end():]
        word_count = len(body.split())

        sources.append({
            "slug": slug,
            "url": url,
            "content": content,
            "word_count": word_count,
        })

    return sources


def find_entries(entries_dir: Path) -> list[dict]:
    """Find entry markdown files."""
    entries = []

    for md_file in sorted(entries_dir.rglob("*.md")):
        content = md_file.read_text()
        rel_path = md_file.relative_to(entries_dir)

        title_match = re.search(r"^#+ (.+)$", content, re.MULTILINE)
        title = title_match.group(1) if title_match else md_file.stem.replace("-", " ").title()

        topic = md_file.stem
        h = hashlib.sha256(f"{topic}:{content[:200]}".encode()).hexdigest()[:12]

        entries.append({
            "id": h,
            "topic": topic,
            "title": title,
            "content": content,
            "path": str(rel_path),
        })

    return entries


def import_batch(client, domain_id, endpoint, key, items, batch_size=200, timeout=120):
    """Import items in batches to avoid request size limits."""
    imported = 0
    skipped = 0
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        resp = client.post(
            f"/api/domains/{domain_id}/{endpoint}",
            json={key: batch},
            timeout=timeout,
        )
        if resp.status_code == 200:
            result = resp.json()
            imported += result.get("imported", 0)
            skipped += result.get("skipped", 0)
        else:
            print(f"    Error on batch {i}-{i+len(batch)}: {resp.status_code} {resp.text[:200]}")
    return imported, skipped


def main():
    parser = argparse.ArgumentParser(description="Import meta-expert repo into a reasons-service domain")
    parser.add_argument("repo_path", type=Path, help="Path to meta-expert repo (e.g., ~/git/redhat-expert)")
    parser.add_argument("--name", required=True, help="Domain name")
    parser.add_argument("--domain", required=True, help="Domain subject area")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Service base URL")
    parser.add_argument("--domain-id", help="Use existing domain ID instead of creating new")
    parser.add_argument("--clusters", nargs="*", help="Import only these clusters (default: all)")
    parser.add_argument("--chunk", action="store_true", help="Trigger chunk backfill after import")
    parser.add_argument("--api-key", help="API key (or set EXPERT_API_KEY)")
    args = parser.parse_args()

    repo = args.repo_path.expanduser().resolve()
    if not repo.is_dir():
        print(f"Error: {repo} is not a directory")
        sys.exit(1)

    # Resolve auth: --api-key > EXPERT_API_KEY > Google OAuth token
    headers = {}
    api_key = args.api_key or os.environ.get("EXPERT_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif TOKEN_PATH.is_file():
        token_data = json.loads(TOKEN_PATH.read_text())
        id_token = token_data.get("id_token")
        if id_token:
            headers["Authorization"] = f"Bearer {id_token}"
            print(f"Using Google OAuth token from {TOKEN_PATH}")

    client = httpx.Client(base_url=args.base_url, timeout=30, headers=headers)

    # 1. Create or use existing domain
    if args.domain_id:
        domain_id = args.domain_id
        resp = client.get(f"/api/domains/{domain_id}")
        if resp.status_code != 200:
            print(f"Error: domain {domain_id} not found")
            sys.exit(1)
        print(f"Using existing domain: {domain_id}")
    else:
        resp = client.post("/api/domains", json={"name": args.name, "description": args.domain})
        if resp.status_code == 200:
            domain_id = resp.json()["id"]
            print(f"Created domain: {args.name} ({domain_id})")
        else:
            print(f"Error creating domain: {resp.text}")
            sys.exit(1)

    # 2. Discover clusters
    all_clusters = discover_clusters(repo)
    clusters = args.clusters if args.clusters else all_clusters
    print(f"\nClusters: {', '.join(clusters)}")

    total_sources = 0
    total_entries = 0
    total_beliefs = 0

    # 3. Import each cluster
    for cluster in clusters:
        cluster_dir = repo / cluster
        print(f"\n{'='*60}")
        print(f"Cluster: {cluster}")
        print(f"{'='*60}")

        # Sources
        sources_dir = cluster_dir / "sources"
        if sources_dir.is_dir():
            sources = find_sources(sources_dir, cluster)
            print(f"  Sources: {len(sources)} files")
            if sources:
                imported, skipped = import_batch(
                    client, domain_id, "import/sources", "sources", sources,
                )
                print(f"    Imported: {imported}, Skipped: {skipped}")
                total_sources += imported
        else:
            print(f"  Sources: (none)")

        # Entries
        entries_dir = cluster_dir / "entries"
        if entries_dir.is_dir():
            entries = find_entries(entries_dir)
            print(f"  Entries: {len(entries)} files")
            if entries:
                imported, skipped = import_batch(
                    client, domain_id, "import/entries", "entries", entries,
                )
                print(f"    Imported: {imported}, Skipped: {skipped}")
                total_entries += imported
        else:
            print(f"  Entries: (none)")

        # Beliefs
        beliefs_path = cluster_dir / "beliefs.md"
        if beliefs_path.is_file():
            claims = parse_beliefs(beliefs_path)
            print(f"  Beliefs: {len(claims)} claims")
            if claims:
                imported, skipped = import_batch(
                    client, domain_id, "import/beliefs", "claims", claims,
                    batch_size=500, timeout=300,
                )
                print(f"    Imported: {imported}, Skipped: {skipped}")
                total_beliefs += imported
        else:
            print(f"  Beliefs: (none)")

    # 4. Top-level entries (cross-domain analysis, etc.)
    top_entries_dir = repo / "entries"
    if top_entries_dir.is_dir():
        entries = find_entries(top_entries_dir)
        if entries:
            print(f"\n{'='*60}")
            print(f"Top-level entries: {len(entries)} files")
            print(f"{'='*60}")
            imported, skipped = import_batch(
                client, domain_id, "import/entries", "entries", entries,
            )
            print(f"  Imported: {imported}, Skipped: {skipped}")
            total_entries += imported

    # 5. Top-level beliefs
    top_beliefs = repo / "beliefs.md"
    if top_beliefs.is_file():
        claims = parse_beliefs(top_beliefs)
        if claims:
            print(f"\nTop-level beliefs: {len(claims)} claims")
            imported, skipped = import_batch(
                client, domain_id, "import/beliefs", "claims", claims,
                batch_size=500, timeout=300,
            )
            print(f"  Imported: {imported}, Skipped: {skipped}")
            total_beliefs += imported

    # 6. Chunk backfill
    if args.chunk:
        print(f"\nChunking sources...")
        resp = client.post(
            f"/api/domains/{domain_id}/chunk-sources",
            timeout=600,
        )
        if resp.status_code == 200:
            result = resp.json()
            print(f"  Chunked: {result['sources_chunked']} sources, {result['total_chunks']} chunks")
        else:
            print(f"  Error: {resp.status_code} {resp.text[:200]}")

    # Summary
    print(f"\n{'='*60}")
    print(f"Import complete")
    print(f"  New sources: {total_sources}")
    print(f"  New entries: {total_entries}")
    print(f"  New beliefs: {total_beliefs}")

    resp = client.get(f"/api/domains/{domain_id}")
    if resp.status_code == 200:
        p = resp.json()
        print(f"\nDomain totals: {p['name']}")
        print(f"  Sources: {p['source_count']}")
        print(f"  Entries: {p['entry_count']}")
        print(f"  Beliefs: {p['belief_count']}")


if __name__ == "__main__":
    main()
