#!/usr/bin/env bash
# Sign in, get a document, mint a fresh ticket, run the probe.
#
#   ./scripts/connect.sh              echo test
#   ./scripts/connect.sh --flood      backpressure / 4008
#   ./scripts/connect.sh --no-hello   protocol error / 4002
#   ./scripts/connect.sh --silent     hello deadline
#
#   DOC=<uuid> ./scripts/connect.sh   reuse an existing document
#   EMAIL=bob@example.com ./scripts/connect.sh
set -euo pipefail

BASE=${BASE:-http://localhost:8000}
EMAIL=${EMAIL:-sanjay@example.com}
PASS=${PASS:-password123}

# Pull one field out of a JSON response, or explain what came back instead.
field() {
    python3 -c "
import sys, json
raw = sys.stdin.read()
if not raw.strip():
    sys.exit('  server sent an empty response — is uvicorn running on $BASE ?')
try:
    print(json.loads(raw)['$1'])
except json.JSONDecodeError:
    sys.exit(f'  not JSON: {raw[:200]}')
except KeyError:
    sys.exit(f'  no \'$1\' in response: {raw[:200]}')
"
}

if ! curl -sf --max-time 3 -o /dev/null "$BASE/healthz"; then
    echo "cannot reach $BASE/healthz — start the server first:" >&2
    echo "    uv run uvicorn app.main:app --reload" >&2
    exit 1
fi

TOKEN=$(curl -s -X POST "$BASE/api/auth/signin" \
    -H 'content-type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" | field access_token)

DOC=${DOC:-$(curl -s -X POST "$BASE/api/docs" \
    -H "authorization: Bearer $TOKEN" \
    -H 'content-type: application/json' \
    -d '{"title":"Probe Doc"}' | field id)}

# Tickets live 30s and burn on first use, so mint it last.
TICKET=$(curl -s -X POST "$BASE/api/docs/$DOC/ticket" \
    -H "authorization: Bearer $TOKEN" | field ticket)

echo "doc=$DOC"
exec uv run python scripts/probe.py "${BASE/http/ws}/ws?doc=$DOC&ticket=$TICKET" "$@"
