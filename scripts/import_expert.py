#!/usr/bin/env python3
"""Import sources, entries, and summaries from a file-based expert repo into reasons-service.

For beliefs, use scripts/upload_reasons_db.sh which does bulk upsert (much faster).

Usage:
    python scripts/import_expert.py ~/git/aap-expert --name aap-expert --domain "Ansible Automation Platform 2.6"
    python scripts/import_expert.py ~/git/code-expert --name code-expert --domain "Code Analysis"
"""

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"



def find_sources(sources_dir: Path) -> list[dict]:
    """Find all source markdown files and parse them."""
    sources = []

    for md_file in sorted(sources_dir.rglob("*.md")):
        content = md_file.read_text()
        slug = md_file.stem

        # Extract URL from YAML frontmatter
        url = None
        fm_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if fm_match:
            for line in fm_match.group(1).split("\n"):
                if line.startswith("source:"):
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
    """Find all entry markdown files and parse them."""
    entries = []

    for md_file in sorted(entries_dir.rglob("*.md")):
        content = md_file.read_text()
        rel_path = md_file.relative_to(entries_dir)

        # Extract title from first heading
        title_match = re.search(r"^#+ (.+)$", content, re.MULTILINE)
        title = title_match.group(1) if title_match else md_file.stem.replace("-", " ").title()

        # Use filename stem as topic
        topic = md_file.stem

        # Generate deterministic ID
        h = hashlib.sha256(f"{topic}:{content[:200]}".encode()).hexdigest()[:12]

        entries.append({
            "id": h,
            "topic": topic,
            "title": title,
            "content": content,
            "path": str(rel_path),
        })

    return entries


def find_summaries(summaries_dir: Path) -> list[dict]:
    """Find all summary markdown files and parse them."""
    summaries = []

    for md_file in sorted(summaries_dir.rglob("*.md")):
        content = md_file.read_text()
        rel_path = md_file.relative_to(summaries_dir)

        title_match = re.search(r"^#+ (.+)$", content, re.MULTILINE)
        title = title_match.group(1) if title_match else md_file.stem.replace("-", " ").title()

        topic = md_file.stem

        h = hashlib.sha256(f"{topic}:{content[:200]}".encode()).hexdigest()[:12]

        summaries.append({
            "id": h,
            "topic": topic,
            "title": title,
            "content": content,
            "path": str(rel_path),
        })

    return summaries


def main():
    parser = argparse.ArgumentParser(description="Import expert repo into a reasons-service domain")
    parser.add_argument("repo_path", type=Path, help="Path to expert repo (e.g., ~/git/aap-expert)")
    parser.add_argument("--name", required=True, help="Domain name")
    parser.add_argument("--domain", required=True, help="Domain subject area")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Service base URL")
    parser.add_argument("--api-key", default=os.environ.get("REASONS_SERVICE_API_KEY", os.environ.get("EXPERT_SERVICE_API_KEY", "")), help="API key for authentication")
    parser.add_argument("--domain-id", help="Use existing domain ID instead of creating new")
    args = parser.parse_args()

    repo = args.repo_path.expanduser().resolve()
    if not repo.is_dir():
        print(f"Error: {repo} is not a directory")
        sys.exit(1)

    headers = {}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    client = httpx.Client(base_url=args.base_url, headers=headers, timeout=30)

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

    # 2. Import sources
    sources_dir = repo / "sources"
    if sources_dir.is_dir():
        sources = find_sources(sources_dir)
        print(f"\nImporting {len(sources)} sources...")

        resp = client.post(
            f"/api/domains/{domain_id}/import/sources",
            json={"sources": sources},
            timeout=60,
        )
        if resp.status_code == 200:
            result = resp.json()
            print(f"  Imported: {result.get('imported', 0)}, Skipped: {result.get('skipped', 0)}")
        else:
            print(f"  Error: {resp.status_code} {resp.text}")
    else:
        print(f"No sources directory at {sources_dir}")

    # 3. Import entries
    entries_dir = repo / "entries"
    if entries_dir.is_dir():
        entries = find_entries(entries_dir)
        print(f"\nImporting {len(entries)} entries...")

        resp = client.post(
            f"/api/domains/{domain_id}/import/entries",
            json={"entries": entries},
            timeout=60,
        )
        if resp.status_code == 200:
            result = resp.json()
            print(f"  Imported: {result.get('imported', 0)}, Skipped: {result.get('skipped', 0)}")
        else:
            print(f"  Error: {resp.status_code} {resp.text}")
    else:
        print(f"No entries directory at {entries_dir}")

    # 4. Import summaries
    summaries_dir = repo / "summaries"
    if summaries_dir.is_dir():
        summaries = find_summaries(summaries_dir)
        print(f"\nImporting {len(summaries)} summaries...")

        resp = client.post(
            f"/api/domains/{domain_id}/import/summaries",
            json={"summaries": summaries},
            timeout=60,
        )
        if resp.status_code == 200:
            result = resp.json()
            print(f"  Imported: {result.get('imported', 0)}, Skipped: {result.get('skipped', 0)}, Linked: {result.get('linked', 0)}")
        else:
            print(f"  Error: {resp.status_code} {resp.text}")
    else:
        print(f"No summaries directory at {summaries_dir}")

    # Summary
    resp = client.get(f"/api/domains/{domain_id}")
    if resp.status_code == 200:
        p = resp.json()
        print(f"\nDomain: {p['name']}")
        print(f"  Sources: {p['source_count']}")
        print(f"  Entries: {p['entry_count']}")
        print(f"  Summaries: {p.get('summary_count', 'N/A')}")
        print(f"  Beliefs: {p['belief_count']}")


if __name__ == "__main__":
    main()
