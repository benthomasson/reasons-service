#!/usr/bin/env python3
"""Load a reasons.db (SQLite) into reasons-service's PostgreSQL via bulk SQL.

Optionally loads entries and sources from the expert repo directory.

Usage:
    python scripts/load_reasons_db.py <reasons.db path> <domain_name> [--description <desc>] [--entries-dir <path> ...] [--sources-dir <path>]

Examples:
    python scripts/load_reasons_db.py ~/git/redhat-expert/reasons.db redhat-expert --description "Red Hat strategy"
    python scripts/load_reasons_db.py ~/git/ftl-reasons-expert/reasons.db ftl-reasons-expert --description "TMS library" --entries-dir ~/git/ftl-reasons-expert/entries
    python scripts/load_reasons_db.py ~/git/agents-python-meta-expert/reasons.db meta-expert --description "Cross-domain analysis" --entries-dir ~/git/agents-python-meta-expert/entries ~/git/agents-python-expert/entries ~/git/agents-python-project-expert/entries
"""

import hashlib
import json
import re
import sqlite3
import sys
import uuid
from pathlib import Path

import psycopg

# Add parent so we can import reasons_service modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reasons_service.chunking import chunk_markdown


def find_entries(entries_dir: Path) -> list[dict]:
    """Find all entry markdown files and parse them."""
    entries = []
    for md_file in sorted(entries_dir.rglob("*.md")):
        content = md_file.read_text()
        rel_path = md_file.relative_to(entries_dir)

        # Extract title from first heading
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


def _parse_arg(flag: str) -> str | None:
    """Extract a --flag value from sys.argv."""
    if flag in sys.argv:
        idx = sys.argv.index(flag)
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    return None


def _parse_arg_multi(flag: str) -> list[str]:
    """Extract all values after --flag until the next --flag or end of args."""
    values = []
    i = 0
    while i < len(sys.argv):
        if sys.argv[i] == flag:
            i += 1
            while i < len(sys.argv) and not sys.argv[i].startswith("--"):
                values.append(sys.argv[i])
                i += 1
        else:
            i += 1
    return values


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    db_path = sys.argv[1]
    domain_name = sys.argv[2]
    description = _parse_arg("--description") or "general"
    entries_dirs = _parse_arg_multi("--entries-dir")
    sources_dir = _parse_arg("--sources-dir")

    conninfo = "postgresql://ben@localhost:5432/reasons_service"

    # Read from SQLite
    sqlite_conn = sqlite3.connect(db_path)
    sqlite_conn.row_factory = sqlite3.Row

    nodes = sqlite_conn.execute("SELECT * FROM nodes").fetchall()
    justifications = sqlite_conn.execute("SELECT * FROM justifications").fetchall()

    try:
        nogoods = sqlite_conn.execute("SELECT * FROM nogoods").fetchall()
    except sqlite3.OperationalError:
        nogoods = []

    sqlite_conn.close()

    print(f"Read from {db_path}:")
    print(f"  {len(nodes)} nodes, {len(justifications)} justifications, {len(nogoods)} nogoods")

    # Write to PostgreSQL
    pg = psycopg.connect(conninfo)

    with pg.cursor() as cur:
        # Create or get domain
        cur.execute(
            "SELECT id FROM domains WHERE name = %s", (domain_name,)
        )
        row = cur.fetchone()
        if row:
            domain_id = str(row[0])
            print(f"Using existing domain: {domain_name} ({domain_id})")

            # Clear existing RMS data for this domain
            for table in ("rms_propagation_log", "rms_justifications",
                          "rms_nogoods", "rms_network_meta", "rms_nodes"):
                cur.execute(f"DELETE FROM {table} WHERE domain_id = %s", (domain_id,))
            print("  Cleared existing RMS data")
        else:
            cur.execute(
                "INSERT INTO domains (name, description) VALUES (%s, %s) RETURNING id",
                (domain_name, description),
            )
            domain_id = str(cur.fetchone()[0])
            print(f"Created domain: {domain_name} ({domain_id})")

        # Check if SQLite has source_url column
        has_source_url = "source_url" in [k for k in nodes[0].keys()] if nodes else False

        # Bulk insert nodes
        for node in nodes:
            meta = node["metadata_json"] or "{}"
            source_url = (node["source_url"] or "") if has_source_url else ""
            cur.execute(
                "INSERT INTO rms_nodes (id, domain_id, text, truth_value, source, source_url, source_hash, date, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (node["id"], domain_id, node["text"], node["truth_value"],
                 node["source"] or "", source_url, node["source_hash"] or "",
                 node["date"] or "", meta),
            )

        # Bulk insert justifications
        for j in justifications:
            cur.execute(
                "INSERT INTO rms_justifications (node_id, domain_id, type, antecedents, outlist, label) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (j["node_id"], domain_id, j["type"],
                 j["antecedents_json"], j["outlist_json"], j["label"] or ""),
            )

        # Bulk insert nogoods
        for ng in nogoods:
            cur.execute(
                "INSERT INTO rms_nogoods (id, domain_id, nodes, discovered, resolution) "
                "VALUES (%s, %s, %s, %s, %s)",
                (ng["id"], domain_id, ng["nodes_json"] if "nodes_json" in ng.keys() else json.dumps(ng["nodes"]),
                 ng["discovered"] if "discovered" in ng.keys() else "",
                 ng["resolution"] if "resolution" in ng.keys() else ""),
            )

        # Import sources
        source_count = 0
        if sources_dir:
            sources_path = Path(sources_dir).expanduser().resolve()
            if sources_path.is_dir():
                # Clear existing sources (cascades to source_chunks, entry_sources)
                cur.execute("DELETE FROM sources WHERE domain_id = %s", (domain_id,))

                sources = find_sources(sources_path)
                for s in sources:
                    cur.execute(
                        "INSERT INTO sources (domain_id, slug, url, content, word_count) "
                        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (domain_id, slug) DO NOTHING",
                        (domain_id, s["slug"], s["url"], s["content"], s["word_count"]),
                    )
                source_count = len(sources)
                print(f"  {source_count} sources imported")
            else:
                print(f"  Warning: sources dir not found: {sources_path}")

        # Import entries (also as sources + chunks for FTS RAG)
        entry_count = 0
        chunk_count = 0
        if entries_dirs:
            # Clear existing entries and their sources/chunks once before loading
            cur.execute("DELETE FROM entries WHERE domain_id = %s", (domain_id,))
            if not sources_dir:
                cur.execute("DELETE FROM sources WHERE domain_id = %s", (domain_id,))

            for entries_dir in entries_dirs:
                entries_path = Path(entries_dir).expanduser().resolve()
                if not entries_path.is_dir():
                    print(f"  Warning: entries dir not found: {entries_path}")
                    continue

                entries = find_entries(entries_path)
                for e in entries:
                    cur.execute(
                        "INSERT INTO entries (id, domain_id, topic, title, content) "
                        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id, domain_id) DO NOTHING",
                        (e["id"], domain_id, e["topic"], e["title"], e["content"]),
                    )

                    # Also create as a source + chunks so FTS RAG can find them
                    source_id = str(uuid.uuid4())
                    word_count = len(e["content"].split())
                    cur.execute(
                        "INSERT INTO sources (id, domain_id, slug, content, word_count) "
                        "VALUES (%s, %s, %s, %s, %s) "
                        "ON CONFLICT (domain_id, slug) DO UPDATE SET content = EXCLUDED.content, word_count = EXCLUDED.word_count "
                        "RETURNING id",
                        (source_id, domain_id, e["topic"], e["content"], word_count),
                    )
                    source_id = str(cur.fetchone()[0])
                    # Clear old chunks for this source before inserting new ones
                    cur.execute("DELETE FROM source_chunks WHERE source_id = %s", (source_id,))
                    for c in chunk_markdown(e["content"]):
                        cur.execute(
                            "INSERT INTO source_chunks (domain_id, source_id, chunk_index, section, text) "
                            "VALUES (%s, %s, %s, %s, %s)",
                            (domain_id, source_id, c["chunk_index"], c["section"], c["text"]),
                        )
                        chunk_count += 1

                dir_count = len(entries)
                entry_count += dir_count
                print(f"  {dir_count} entries from {entries_path.name} ({entries_path})")

            print(f"  {entry_count} total entries imported ({chunk_count} chunks)")

    pg.commit()
    pg.close()

    in_count = sum(1 for n in nodes if n["truth_value"] == "IN")
    print(f"\nLoaded into domain '{domain_name}':")
    print(f"  {len(nodes)} nodes ({in_count} IN, {len(nodes) - in_count} OUT)")
    print(f"  {len(justifications)} justifications")
    print(f"  {len(nogoods)} nogoods")
    if entries_dirs:
        print(f"  {entry_count} entries ({chunk_count} chunks)")
    if sources_dir:
        print(f"  {source_count} sources")
    print(f"\nTest with:")
    print(f"  reasons-service  # start the server")
    print(f"  # then visit http://localhost:8000/domains/{domain_id}")


if __name__ == "__main__":
    main()
