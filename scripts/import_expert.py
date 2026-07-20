#!/usr/bin/env python3
"""Import entries and beliefs from a file-based expert repo into reasons-service.

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


def parse_beliefs(beliefs_path: Path) -> list[dict]:
    """Parse beliefs.md into a list of claim dicts."""
    text = beliefs_path.read_text()
    claims = []

    # Pattern: ### claim-id [STATUS]
    # Claim text (one or more lines until next marker)
    # - Source: path
    # - Source hash: hash
    # - Date: date
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

        # Extract claim text (first non-empty line(s) before metadata)
        lines = body.split("\n")
        claim_text_lines = []
        source = None
        source_hash = None
        date = None

        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith("- Source:") and "hash" not in line_stripped.lower():
                source = line_stripped.replace("- Source:", "").strip()
            elif line_stripped.startswith("- Source hash:"):
                source_hash = line_stripped.replace("- Source hash:", "").strip()
            elif line_stripped.startswith("- Date:"):
                date = line_stripped.replace("- Date:", "").strip()
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


def main():
    parser = argparse.ArgumentParser(description="Import expert repo into reasons-service")
    parser.add_argument("repo_path", type=Path, help="Path to expert repo (e.g., ~/git/aap-expert)")
    parser.add_argument("--name", required=True, help="Project name")
    parser.add_argument("--domain", required=True, help="Project domain")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Service base URL")
    parser.add_argument("--api-key", default=os.environ.get("EXPERT_SERVICE_API_KEY", ""), help="API key for authentication")
    parser.add_argument("--project-id", help="Use existing project ID instead of creating new")
    args = parser.parse_args()

    repo = args.repo_path.expanduser().resolve()
    if not repo.is_dir():
        print(f"Error: {repo} is not a directory")
        sys.exit(1)

    headers = {}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    client = httpx.Client(base_url=args.base_url, headers=headers, timeout=30)

    # 1. Create or use existing project
    if args.project_id:
        project_id = args.project_id
        resp = client.get(f"/api/projects/{project_id}")
        if resp.status_code != 200:
            print(f"Error: project {project_id} not found")
            sys.exit(1)
        print(f"Using existing project: {project_id}")
    else:
        resp = client.post("/api/projects", json={"name": args.name, "domain": args.domain})
        if resp.status_code == 200:
            project_id = resp.json()["id"]
            print(f"Created project: {args.name} ({project_id})")
        else:
            print(f"Error creating project: {resp.text}")
            sys.exit(1)

    # 2. Import sources
    sources_dir = repo / "sources"
    if sources_dir.is_dir():
        sources = find_sources(sources_dir)
        print(f"\nImporting {len(sources)} sources...")

        resp = client.post(
            f"/api/projects/{project_id}/import/sources",
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
            f"/api/projects/{project_id}/import/entries",
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

    # 4. Import beliefs (batched to avoid timeouts)
    beliefs_path = repo / "beliefs.md"
    if beliefs_path.is_file():
        claims = parse_beliefs(beliefs_path)
        print(f"\nImporting {len(claims)} beliefs...")

        batch_size = 200
        total_imported = 0
        total_skipped = 0
        for i in range(0, len(claims), batch_size):
            batch = claims[i:i + batch_size]
            resp = client.post(
                f"/api/projects/{project_id}/import/beliefs",
                json={"claims": batch},
                timeout=300,
            )
            if resp.status_code == 200:
                result = resp.json()
                total_imported += result.get('imported', 0)
                total_skipped += result.get('skipped', 0)
                print(f"  Batch {i // batch_size + 1}: {result.get('imported', 0)} imported, {result.get('skipped', 0)} skipped")
            else:
                print(f"  Batch {i // batch_size + 1} error: {resp.status_code} {resp.text}")
        print(f"  Total: {total_imported} imported, {total_skipped} skipped")
    else:
        print(f"No beliefs.md at {beliefs_path}")

    # 5. Import nogoods
    nogoods_path = repo / "nogoods.md"
    if nogoods_path.is_file():
        print(f"\nNogoods file found at {nogoods_path} (import not yet implemented)")

    # Summary
    resp = client.get(f"/api/projects/{project_id}")
    if resp.status_code == 200:
        p = resp.json()
        print(f"\nProject: {p['name']}")
        print(f"  Sources: {p['source_count']}")
        print(f"  Entries: {p['entry_count']}")
        print(f"  Beliefs: {p['belief_count']}")


if __name__ == "__main__":
    main()
