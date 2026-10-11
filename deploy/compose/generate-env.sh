#!/bin/sh
# Create .env from .env.example with freshly generated secrets.
# Usage: ./deploy/compose/generate-env.sh [--force]
set -eu

root="$(cd "$(dirname "$0")/../.." && pwd)"
example="$root/.env.example"
target="$root/.env"

if [ -e "$target" ] && [ "${1:-}" != "--force" ]; then
    echo "$target already exists; refusing to overwrite (pass --force to replace it)." >&2
    exit 1
fi

secret() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    else
        od -An -tx1 -N32 /dev/urandom | tr -d ' \n'
    fi
}

umask 077
sed \
    -e "s|^JWT_SECRET=.*|JWT_SECRET=$(secret)|" \
    -e "s|^INTERNAL_API_KEY=.*|INTERNAL_API_KEY=$(secret)|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(secret)|" \
    "$example" > "$target"

echo "Wrote $target with new JWT_SECRET, INTERNAL_API_KEY and POSTGRES_PASSWORD."
echo "Next: docker compose up -d"
