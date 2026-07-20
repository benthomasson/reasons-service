# Source URL Backfill Complete

**Date:** 2026-05-05
**Time:** 09:49

## Summary

Backfilled source_url on 4,255 of 4,358 entry-sourced beliefs (97.6%) in expert-service's rms_nodes table. These URLs point to the original Google Drive documents that each belief was derived from, enabling clickable provenance links in the ## Sources section of chat responses.

## The Problem

Beliefs had a `source` field pointing to the internal entry file (e.g. `entries/2026/04/17/ansible-3-pager.md`) but no link to the original document. The `source_url` column was added to `rms_nodes` to hold the Google Drive URI.

## Where URLs Come From

Two places in each department's `sources/` directory in redhat-expert:

1. **`.manifest.json`** — JSON index mapping every source filename to `{source_id, source_url, name, mime_type}`. Written by `fetch_docs.py` during fetch. Best coverage since it includes all file types.
2. **YAML frontmatter** in `.md` source files — `source_url` field added by `fetch_docs.py --force` during refetch. Only covers markdown files.

Frontmatter takes precedence over manifest when both exist for the same file.

## Matching Challenges

The backfill script (`scripts/backfill_source_urls.py`) normalizes source filenames to kebab-case slugs and matches them against belief source paths. Three normalization mismatches required fixes:

1. **File type mismatch**: Many source files are PDFs/PPTXs that were converted to `.md` during synthesis. The manifest only has the original extension (`IAM.pdf`), not the converted `.md`. Fix: scan all file types in manifests, not just `.md`.

2. **Case sensitivity**: Belief slugs preserved original case (`IAM`) but the URL map used lowercase (`iam`). Fix: normalize belief slugs through `filename_to_slug()` before lookup.

3. **Dot/ampersand hyphenation**: IT wiki files use brackets and dots in names like `[IT AI Platforms] [Models.corp] Getting Started`. The `filename_to_slug()` function converts the dot to a hyphen (`models-corp`), but the entry generator dropped it (`modelscorp`). Same for `M&L` → `m-l` vs `ml`. Fix: compressed fallback index that strips all hyphens before comparison.

## Coverage Progression

| Stage | Coverage | Fix |
|-------|----------|-----|
| Initial | 3,307 / 4,358 (75.9%) | Frontmatter + .md-only manifest scan |
| + All file types | 3,711 (85.2%) | Scan .pdf, .pptx, .csv in manifests |
| + Case normalization | 3,919 (89.9%) | `filename_to_slug()` on belief slugs |
| + Compressed fallback | 4,255 (97.6%) | Hyphen-stripped comparison |

## Remaining Gaps

15 unique source files (103 beliefs) have no manifest or frontmatter match. These are likely files never uploaded to Google Drive or since renamed/deleted. Not worth chasing.
