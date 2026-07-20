"""Build embeddings for a domain's entries, claims, and sources."""

import argparse
import sys
from uuid import UUID

from reasons_service.embeddings import build_embeddings


def main():
    parser = argparse.ArgumentParser(description="Build embeddings for a domain")
    parser.add_argument("--domain-id", required=True, help="Domain UUID")
    args = parser.parse_args()

    try:
        domain_id = UUID(args.domain_id)
    except ValueError:
        print(f"Invalid UUID: {args.domain_id}", file=sys.stderr)
        sys.exit(1)

    print(f"Building embeddings for domain {domain_id}...")
    counts = build_embeddings(domain_id)
    print(
        f"Embedded {counts['entries']} entries, "
        f"{counts['sources']} sources, "
        f"{counts['claims']} claims"
    )


if __name__ == "__main__":
    main()
