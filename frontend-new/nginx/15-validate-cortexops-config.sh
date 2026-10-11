#!/bin/sh
# CORTEXOPS_API_URL is written into a JavaScript string and the CSP header, so only accept a plain origin/URL.
set -eu

url="${CORTEXOPS_API_URL:-}"
if [ -n "$url" ] && ! printf '%s' "$url" | grep -Eq '^https?://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~/-]*)?$'; then
    echo "CORTEXOPS_API_URL must look like https://api.example.com (got: $url)" >&2
    exit 1
fi
echo "CortexOps dashboard: API URL = ${url:-<unset, using build-time default>}"
