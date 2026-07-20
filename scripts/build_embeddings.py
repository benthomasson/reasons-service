"""Build embeddings for a project's entries, claims, and sources."""

import argparse
import sys
from uuid import UUID

from reasons_service.embeddings import build_embeddings


def main():
    parser = argparse.ArgumentParser(description="Build embeddings for a project")
    parser.add_argument("--project-id", required=True, help="Project UUID")
    args = parser.parse_args()

    try:
        project_id = UUID(args.project_id)
    except ValueError:
        print(f"Invalid UUID: {args.project_id}", file=sys.stderr)
        sys.exit(1)

    print(f"Building embeddings for project {project_id}...")
    counts = build_embeddings(project_id)
    print(
        f"Embedded {counts['entries']} entries, "
        f"{counts['sources']} sources, "
        f"{counts['claims']} claims"
    )


if __name__ == "__main__":
    main()
