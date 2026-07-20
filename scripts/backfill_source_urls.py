#!/usr/bin/env python3
"""Backfill source_url on rms_nodes from source file frontmatter and manifests.

Scans department source directories in the redhat-expert repo for:
  1. YAML frontmatter with source_url in .md files
  2. .manifest.json files mapping filenames to source URLs

Then matches belief source paths (entries/YYYY/MM/DD/slug.md) to source
filenames by normalizing to kebab-case slugs.

Usage:
    python scripts/backfill_source_urls.py [--dry-run]
    python scripts/backfill_source_urls.py --redhat-expert ~/git/redhat-expert
    python scripts/backfill_source_urls.py --project-id f1ac8a54-2103-42ec-9ddc-d7cba332b9bd
"""

import argparse
import json
import os
import re

import psycopg


DEPARTMENTS = ["engineering", "product", "marketing", "sales", "hr", "it", "operations"]


def scan_frontmatter(sources_dir: str) -> dict[str, str]:
    """Scan .md files for YAML frontmatter with source_url."""
    url_map = {}
    if not os.path.isdir(sources_dir):
        return url_map
    for fname in os.listdir(sources_dir):
        if not fname.endswith(".md") or fname.endswith(".synth.md"):
            continue
        fpath = os.path.join(sources_dir, fname)
        with open(fpath) as f:
            first = f.readline().strip()
            if first != "---":
                continue
            source_url = ""
            for line in f:
                if line.strip() == "---":
                    break
                if line.startswith("source_url:"):
                    source_url = line.split(":", 1)[1].strip()
            if source_url:
                slug = filename_to_slug(fname.replace(".md", ""))
                url_map[slug] = source_url
    return url_map


def scan_manifest(sources_dir: str) -> dict[str, str]:
    """Scan .manifest.json for source URLs.

    Matches .md files first, then falls back to other formats (.pdf, .pptx, .csv)
    since those are often converted to .md on disk and share the same base slug.
    """
    url_map = {}
    manifest_path = os.path.join(sources_dir, ".manifest.json")
    if not os.path.exists(manifest_path):
        return url_map
    with open(manifest_path) as f:
        manifest = json.load(f)

    # Skip synth files, index files, and meta files
    skip_suffixes = (".synth.md", ".synth.meta.json", ".index.json")

    for fname, meta in manifest.items():
        if any(fname.endswith(s) for s in skip_suffixes):
            continue
        source_url = meta.get("source_url", "")
        if not source_url:
            continue
        # Strip any known extension to get the base name
        base = fname
        for ext in (".md", ".pdf", ".pptx", ".csv", ".xlsx", ".docx", ".json"):
            if base.endswith(ext):
                base = base[:-len(ext)]
                break
        slug = filename_to_slug(base)
        # Don't overwrite — .md entries take priority (processed first alphabetically)
        if slug not in url_map:
            url_map[slug] = source_url
    return url_map


def filename_to_slug(name: str) -> str:
    """Normalize a filename to kebab-case slug for matching.

    'Ansible 3-Pager' → 'ansible-3-pager'
    '01. CY26 Product Strategy' → '01-cy26-product-strategy'
    """
    return re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()


def scan_manifest_by_filename(sources_dir: str) -> dict[str, str]:
    """Scan .manifest.json returning original filename → source_url.

    Used for matching sources.slug (e.g. "product/Original Filename")
    where the filename is preserved as-is, not kebab-cased.
    """
    url_map = {}
    manifest_path = os.path.join(sources_dir, ".manifest.json")
    if not os.path.exists(manifest_path):
        return url_map
    with open(manifest_path) as f:
        manifest = json.load(f)

    skip_suffixes = (".synth.md", ".synth.meta.json", ".index.json")

    for fname, meta in manifest.items():
        if any(fname.endswith(s) for s in skip_suffixes):
            continue
        source_url = meta.get("source_url", "")
        if not source_url:
            continue
        # Strip extension to get the base name (matching sources.slug format)
        base = fname
        for ext in (".md", ".pdf", ".pptx", ".csv", ".xlsx", ".docx", ".json"):
            if base.endswith(ext):
                base = base[:-len(ext)]
                break
        if base not in url_map:
            url_map[base] = source_url
    return url_map


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redhat-expert", default=os.path.expanduser("~/git/redhat-expert"),
                        help="Path to redhat-expert repo")
    parser.add_argument("--project-id", default="f1ac8a54-2103-42ec-9ddc-d7cba332b9bd",
                        help="Project UUID in reasons_service DB")
    parser.add_argument("--conninfo", default="postgresql://ben@localhost:5432/reasons_service",
                        help="PostgreSQL connection string")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be updated without writing")
    args = parser.parse_args()

    # Build slug → URL map from all departments
    url_map: dict[str, str] = {}
    # Also build dept/filename → URL map for the sources table
    filename_map: dict[str, str] = {}
    for dept in DEPARTMENTS:
        sources_dir = os.path.join(args.redhat_expert, dept, "sources")
        from_frontmatter = scan_frontmatter(sources_dir)
        from_manifest = scan_manifest(sources_dir)
        from_manifest_filenames = scan_manifest_by_filename(sources_dir)
        # Frontmatter takes precedence over manifest
        combined = {**from_manifest, **from_frontmatter}
        if combined:
            print(f"  {dept}: {len(combined)} URLs ({len(from_frontmatter)} frontmatter, {len(from_manifest)} manifest)")
        url_map.update(combined)
        # Key by "dept/filename" for sources table matching
        for base, url in from_manifest_filenames.items():
            filename_map[f"{dept}/{base}"] = url

    print(f"\n{len(url_map)} total source URLs found")
    print(f"{len(filename_map)} filename-keyed URLs for sources table\n")

    if not url_map:
        print("No source URLs found. Run the refetch script on department sources first.")
        return

    conn = psycopg.connect(args.conninfo)
    cur = conn.cursor()

    # --- Pass 1: rms_nodes (beliefs) ---
    cur.execute(
        "SELECT id, source FROM rms_nodes WHERE project_id = %s AND source LIKE %s AND (source_url = '' OR source_url IS NULL)",
        (args.project_id, "entries/%"),
    )
    rows = cur.fetchall()
    print(f"{len(rows)} beliefs without source_url")

    # Build compressed fallback index (strip hyphens) for entries like
    # Models.corp → "models-corp" vs "modelscorp", M&L → "m-l" vs "ml"
    compressed_map = {k.replace("-", ""): v for k, v in url_map.items()}

    updated = 0
    for node_id, source in rows:
        raw_slug = source.rsplit("/", 1)[-1].replace(".md", "")
        slug = filename_to_slug(raw_slug)
        url = url_map.get(slug) or compressed_map.get(slug.replace("-", ""))
        if url:
            if args.dry_run:
                print(f"  [dry-run] {node_id}: {url}")
            else:
                cur.execute(
                    "UPDATE rms_nodes SET source_url = %s WHERE id = %s AND project_id = %s",
                    (url, node_id, args.project_id),
                )
            updated += 1

    action = "Would update" if args.dry_run else "Updated"
    print(f"\n{action} {updated} beliefs with source_url")
    if rows:
        print(f"Coverage: {updated}/{len(rows)} unlinked beliefs ({updated * 100 // len(rows)}%)")

    # --- Pass 2: sources table (FTS chunks) ---
    cur.execute(
        "SELECT id, slug FROM sources WHERE project_id = %s AND (url = '' OR url IS NULL)",
        (args.project_id,),
    )
    source_rows = cur.fetchall()
    print(f"\n{len(source_rows)} sources without url")

    source_updated = 0
    for source_id, slug in source_rows:
        url = filename_map.get(slug)
        if url:
            if args.dry_run:
                print(f"  [dry-run] source {slug}: {url}")
            else:
                cur.execute(
                    "UPDATE sources SET url = %s WHERE id = %s",
                    (url, source_id),
                )
            source_updated += 1

    print(f"{action} {source_updated} sources with url")
    if source_rows:
        print(f"Coverage: {source_updated}/{len(source_rows)} unlinked sources ({source_updated * 100 // len(source_rows)}%)")

    if not args.dry_run:
        conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
