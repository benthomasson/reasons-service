#!/bin/bash
# Upload a reasons.db to a reasons-service instance.
#
# Upserts into an existing domain (by name), or creates a new one.
#
# Usage:
#   ./scripts/upload_reasons_db.sh <reasons.db> <domain-name> [base-url]
#
# Environment:
#   REASONS_SERVICE_API_KEY  — required
#   REASONS_SERVICE_URL      — alternative to passing base-url as argument
#
# Examples:
#   ./scripts/upload_reasons_db.sh ~/git/eem-expert/reasons.db eem-expert
#   ./scripts/upload_reasons_db.sh ~/git/my-project/reasons.db my-project https://ftl.reasonsforge.com

set -euo pipefail

if [ $# -lt 2 ]; then
    echo "Usage: $0 <reasons.db> <domain-name> [base-url]"
    exit 1
fi

DB_PATH="$1"
DOMAIN_NAME="$2"
BASE_URL="${3:-${REASONS_SERVICE_URL:-}}"

if [ -z "$BASE_URL" ]; then
    echo "Error: base URL not provided. Pass as 3rd argument or set REASONS_SERVICE_URL"
    exit 1
fi

if [ -z "${REASONS_SERVICE_API_KEY:-}" ]; then
    echo "Error: REASONS_SERVICE_API_KEY not set"
    exit 1
fi

if [ ! -f "$DB_PATH" ]; then
    echo "Error: $DB_PATH not found"
    exit 1
fi

AUTH="Authorization: Bearer $REASONS_SERVICE_API_KEY"

# Try to resolve domain name to ID
echo "Resolving domain: $DOMAIN_NAME"
RESOLVE=$(curl -sf -H "$AUTH" "$BASE_URL/api/domains/resolve?name=$DOMAIN_NAME" 2>/dev/null || echo "")

if [ -n "$RESOLVE" ]; then
    DOMAIN_ID=$(echo "$RESOLVE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
    echo "Found domain: $DOMAIN_ID"
    echo "Uploading $DB_PATH (upsert)..."
    curl -X POST "$BASE_URL/api/domains/$DOMAIN_ID/import-reasons" \
        -H "$AUTH" \
        -F "file=@$DB_PATH" \
        -w "\nHTTP %{http_code}\n"
else
    echo "Domain not found, creating: $DOMAIN_NAME"
    echo "Uploading $DB_PATH (new domain)..."
    curl -X POST "$BASE_URL/api/domains/import-reasons" \
        -H "$AUTH" \
        -F "name=$DOMAIN_NAME" \
        -F "description=$DOMAIN_NAME" \
        -F "file=@$DB_PATH" \
        -w "\nHTTP %{http_code}\n"
fi
