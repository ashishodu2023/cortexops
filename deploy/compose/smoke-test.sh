#!/usr/bin/env bash
# End-to-end check of a running compose stack (`docker compose up -d`):
# health of every service, first-key bootstrap, dashboard runtime config and headers, CORS,
# dashboard sign-in (token exchange) and an SDK trace landing in the API.
# Requires curl and a Python with the cortexops SDK installed (pip install ./sdk).
set -euo pipefail

cd "$(dirname "$0")/../.."
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

API="http://localhost:${API_PORT:-8000}"
DASHBOARD="http://localhost:${DASHBOARD_PORT:-3000}"
PROJECT="${CORTEXOPS_PROJECT:-my-agent}"
EXPECTED_API_URL="${CORTEXOPS_API_URL:-http://localhost:8000}"
ORIGIN="${CORS_ORIGINS:-http://localhost:3000}"
ORIGIN="${ORIGIN%%,*}"

fail() {
    echo "FAIL: $*" >&2
    docker compose ps -a >&2 || true
    exit 1
}

container_state() {
    local cid
    cid="$(docker compose ps -aq "$1")"
    [ -n "$cid" ] || { echo missing; return; }
    docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}} {{.State.ExitCode}}{{end}}' "$cid"
}

wait_for() {
    local service="$1" want="$2" state=""
    for _ in $(seq 1 90); do
        state="$(container_state "$service")"
        [ "$state" = "$want" ] && { echo "ok: $service is $want"; return 0; }
        sleep 5
    done
    docker compose logs --tail 80 "$service" >&2 || true
    fail "$service did not reach '$want' (last state: $state)"
}

for service in postgres redis api worker dashboard; do
    wait_for "$service" healthy
done
wait_for bootstrap "exited 0"

curl -fsS "$API/health" | grep -q '"environment":"production"' || fail "API is not running in production mode"
echo "ok: API healthy in production mode"

bootstrap_logs="$(docker compose logs --no-log-prefix bootstrap)"
KEY="$(sed -n 's/.*CORTEXOPS_API_KEY=\(cxo-[0-9a-f]*\).*/\1/p' <<<"$bootstrap_logs" | tail -n 1)"
if [ -n "$KEY" ]; then
    echo "ok: bootstrap issued the first API key for '$PROJECT'"
elif [ -n "${SMOKE_API_KEY:-}" ] && grep -q "already has an active API key" <<<"$bootstrap_logs"; then
    # Re-run against an existing install: bootstrap must be a no-op and the earlier key must still work.
    KEY="$SMOKE_API_KEY"
    echo "ok: bootstrap left the existing key for '$PROJECT' in place"
else
    fail "bootstrap did not print an API key (set SMOKE_API_KEY to re-test an existing install)"
fi

curl -fsS "$API/v1/admin/keys?project=$PROJECT" -H "X-Internal-Key: ${INTERNAL_API_KEY:?}" \
    | grep -q "\"tier\":\"${BOOTSTRAP_TIER:-pro}\"" || fail "bootstrapped key is not on the '${BOOTSTRAP_TIER:-pro}' tier"
echo "ok: bootstrapped key is on the '${BOOTSTRAP_TIER:-pro}' tier"

config_js="$(curl -fsS "$DASHBOARD/config.js")"
grep -qF "apiUrl: \"$EXPECTED_API_URL\"" <<<"$config_js" || fail "dashboard config.js has the wrong API URL: $config_js"
curl -fsS "$DASHBOARD/" | grep -q 'src="/config.js"' || fail "dashboard index.html does not load /config.js"
headers="$(curl -fsSI "$DASHBOARD/")"
grep -qi "content-security-policy:.*connect-src 'self' $EXPECTED_API_URL" <<<"$headers" || fail "dashboard CSP missing API origin"
grep -qi "x-frame-options: DENY" <<<"$headers" || fail "dashboard security headers missing"
echo "ok: dashboard serves runtime config ($EXPECTED_API_URL) with security headers"

preflight="$(curl -fsS -o /dev/null -D - -X OPTIONS "$API/v1/traces" \
    -H "Origin: $ORIGIN" -H "Access-Control-Request-Method: GET" -H "Access-Control-Request-Headers: authorization")"
grep -qi "access-control-allow-origin: $ORIGIN" <<<"$preflight" || fail "CORS preflight from $ORIGIN rejected"
echo "ok: CORS allows $ORIGIN"

CORTEXOPS_API_URL="$API" CORTEXOPS_API_KEY="$KEY" SMOKE_PROJECT="$PROJECT" python - <<'PY'
import os
import uuid

import httpx

from cortexops import CortexTracer
from cortexops.client import CortexClient

api, key, project = os.environ["CORTEXOPS_API_URL"], os.environ["CORTEXOPS_API_KEY"], os.environ["SMOKE_PROJECT"]
marker = f"smoke-{uuid.uuid4().hex[:8]}"

# The API assigns its own trace IDs, so tag the trace with a unique prompt version to find it again.
tracer = CortexTracer(project=project, api_key=key, api_url=api, environment="production")
tracer.set_prompt("smoke-test", marker)
agent = tracer.wrap(lambda inp: {"output": f"echo {inp['input']}"})
agent({"input": "hello from the smoke test"})

listed = CortexClient(api_key=key, base_url=api).list_traces(project, limit=20)
assert any(t.get("prompt_version") == marker for t in listed), "SDK trace not found via API key"

token = httpx.post(f"{api}/v1/auth/token/issue", headers={"X-API-Key": key}, timeout=10).json()["access_token"]
r = httpx.get(f"{api}/v1/traces", params={"project": project}, headers={"Authorization": f"Bearer {token}"}, timeout=10)
r.raise_for_status()
assert any(t.get("prompt_version") == marker for t in r.json()), "trace not visible with a dashboard session token"
print(f"ok: SDK trace ({marker}) is visible to the dashboard session")
PY

echo "Self-hosted stack passed the smoke test."
