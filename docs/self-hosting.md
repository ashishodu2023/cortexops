# Self-hosting CortexOps

CortexOps runs entirely on your own infrastructure: the API, the Celery worker that runs server-side evals,
the dashboard, PostgreSQL and Redis. Nothing calls back to getcortexops.com, and billing is off by default.

There are two supported ways to run it:

- **Docker Compose** (this page): one machine, one command. Good for teams, evaluation and small production installs.
- **Kubernetes**: the Helm chart in [`deploy/helm/cortexops`](../deploy/helm/cortexops/README.md).

## Requirements

- Docker Engine 24+ with the Compose v2 plugin (`docker compose version`).
- 2 vCPU and 2 GB RAM for the whole stack; 10 GB of disk for PostgreSQL to start with.
- `openssl` (optional, used by `generate-env.sh` to create secrets).
- Outbound internet is only needed to pull or build images, plus any integrations you enable
  (OpenAI for the LLM judge, Slack/webhooks for alerts, Resend/SendGrid for email).

## Quickstart

```bash
git clone https://github.com/ashishodu2023/cortexops.git
cd cortexops

./deploy/compose/generate-env.sh      # writes .env (mode 600) with random secrets
docker compose up -d                  # builds the images on first run
docker compose logs bootstrap         # prints your first API key, once
```

| Service | URL | Notes |
|---|---|---|
| Dashboard | http://localhost:3000 | Sign in with the `cxo-` key from `docker compose logs bootstrap` |
| API | http://localhost:8000 | `GET /health`; interactive docs are disabled in production mode |

Point the SDK at your deployment:

```bash
export CORTEXOPS_API_URL=http://localhost:8000
export CORTEXOPS_API_KEY=cxo-...           # from the bootstrap logs
```

```python
from cortexops import CortexTracer

tracer = CortexTracer(project="my-agent")   # reads CORTEXOPS_API_URL / CORTEXOPS_API_KEY
agent = tracer.wrap(my_agent)
```

`./deploy/compose/smoke-test.sh` checks a running stack end to end: service health, the bootstrapped key,
dashboard runtime config and security headers, CORS, dashboard sign-in and an SDK trace round trip.
It needs `curl` and a Python with the SDK installed (`pip install ./sdk httpx`).

### What `docker compose up -d` starts

| Service | Image | Purpose | Healthcheck |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | Primary database (volume `postgres_data`) | `pg_isready` |
| `redis` | `redis:7-alpine` | Celery broker and results, append-only (volume `redis_data`) | `redis-cli ping` |
| `api` | built from `Dockerfile` | FastAPI backend on port 8000; creates the schema on startup | `GET /health` |
| `worker` | same image as `api` | Celery worker for server-side evals | `celery inspect ping` |
| `bootstrap` | same image as `api` | One-shot: creates the first API key, then exits | n/a (exits 0) |
| `dashboard` | built from `frontend-new/Dockerfile` | Vite build served by unprivileged nginx on 8080 | `GET /healthz` |

Start order is enforced with `depends_on` health conditions: postgres and redis, then the API,
then the worker, bootstrap and dashboard. All long-running containers restart `unless-stopped`, run with
`no-new-privileges` and a read-only root filesystem, and the API and dashboard images run as non-root users.

Ports are published on `127.0.0.1` by default. To reach the stack from other machines, put a reverse proxy
in front (see [TLS and reverse proxy](#tls-and-reverse-proxy)) or set `API_BIND=0.0.0.0` and `DASHBOARD_BIND=0.0.0.0`.

## First API key

On first start the `bootstrap` service calls `POST /v1/keys/bootstrap` for `CORTEXOPS_PROJECT` and prints the raw key.
The key is stored only as a SHA-256 hash and cannot be shown again. The service is idempotent: once the project has an
active key it prints "already has an active API key" and exits 0, so it is safe on every `docker compose up`.

Bootstrapped keys are upgraded to `BOOTSTRAP_TIER` (default `pro`) with the admin API, so a self-hosted install is not
held to the hosted free-tier limits (5,000 traces per month, no LLM judge, alerts or prompt versioning).

Lost the key, or need more? Use the admin API with `INTERNAL_API_KEY` from `.env`:

```bash
source .env
# Issue another key for a project
curl -X POST http://localhost:8000/v1/keys -H "X-Internal-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" -d '{"project": "my-agent", "name": "ci"}'
# List keys, then upgrade or revoke by id
curl http://localhost:8000/v1/admin/keys -H "X-Internal-Key: $INTERNAL_API_KEY"
curl -X POST http://localhost:8000/v1/admin/keys/<id>/upgrade -H "X-Internal-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" -d '{"tier": "pro", "scope": "read_write"}'
curl -X POST http://localhost:8000/v1/admin/keys/<id>/revoke -H "X-Internal-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" -d '{"reason": "rotated"}'
```

Notes on the bootstrap endpoint: in production it requires an email (`BOOTSTRAP_EMAIL`, stored in the auth audit log
only), it is rate limited to 5 requests per hour per client, and project names must be 3-64 lowercase letters, digits,
`-` and `_` (names such as `default`, `test`, `demo` and `admin` are reserved).

## Configuration

Compose reads `.env` from the repository root. [`.env.example`](../.env.example) lists every variable with safe
defaults; `generate-env.sh` copies it and fills in the three required secrets.

### Required

| Variable | Description |
|---|---|
| `JWT_SECRET` | Signs dashboard session tokens. Use 32+ random bytes; must not contain `dev`. |
| `INTERNAL_API_KEY` | Admin key for `X-Internal-Key` requests (issuing, upgrading and revoking keys). |
| `POSTGRES_PASSWORD` | Password for the bundled PostgreSQL. URL-safe characters only, since it is embedded in `DATABASE_URL`. |

Changing `JWT_SECRET` signs everyone out. `POSTGRES_PASSWORD` is applied only when the database volume is first
created; to rotate it later, change it in PostgreSQL (`ALTER USER`) and in `.env` together.

### Core

| Variable | Default | Description |
|---|---|---|
| `ENVIRONMENT` | `production` | `production` hides `/docs`, refuses SQLite and requires an email for key bootstrap. |
| `DEBUG` | `false` | Verbose error output. Keep off in production. |
| `CORS_ORIGINS` | `http://localhost:3000` | Browser origins allowed to call the API, comma-separated or a JSON array. Must include the dashboard URL. |
| `CORTEXOPS_API_URL` | `http://localhost:8000` | API URL as seen by the browser. Written into the dashboard at container start and added to its CSP `connect-src`. Must be `http(s)://host[:port][/path]`. |
| `FRONTEND_URL` | `http://localhost:3000` | Public dashboard URL, used in billing redirect links. |
| `TRUSTED_PROXIES` | private ranges | Peers whose `X-Forwarded-For` is trusted, as comma-separated IPs/CIDRs or `*` (see [TLS and reverse proxy](#tls-and-reverse-proxy)). |
| `BILLING_ENABLED` | `false` | Hosted-service billing. When `true`, production startup requires `PAYPAL_WEBHOOK_ID`. |
| `RUN_MIGRATIONS` | `1` | Run database migrations when the API starts (see [Upgrades](#upgrades)). Only the `api` service gets it. |
| `APP_NAME` | `CortexOps API` | Name reported by the API (not passed by default; add it to `docker-compose.yml` to change it). |
| `API_KEY_HEADER` | `X-API-Key` | Header carrying API keys (not passed by default; the SDK and dashboard expect the default). |

### Database and Redis

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_DB` | `cortexops` | Bundled database user and name. |
| `POSTGRES_HOST` / `POSTGRES_PORT` | `postgres` / `5432` | Point at an external PostgreSQL (see [External database](#external-database-and-redis)). |
| `REDIS_URL` | `redis://redis:6379/0` | Redis for the API. |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | Celery broker. |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/1` | Celery results. |
| `WORKER_CONCURRENCY` | `4` | Celery worker processes. |

The API and worker receive `DATABASE_URL=postgresql+asyncpg://POSTGRES_USER:POSTGRES_PASSWORD@POSTGRES_HOST:POSTGRES_PORT/POSTGRES_DB`.

### First key, ports and images

| Variable | Default | Description |
|---|---|---|
| `CORTEXOPS_PROJECT` | `my-agent` | Project the bootstrap service creates a key for. |
| `BOOTSTRAP_EMAIL` | `admin@localhost` | Email recorded with the bootstrap request (required in production). |
| `BOOTSTRAP_TIER` | `pro` | Tier of the bootstrapped key (`pro` or `free`). |
| `API_BIND` / `API_PORT` | `127.0.0.1` / `8000` | Host interface and port for the API. |
| `DASHBOARD_BIND` / `DASHBOARD_PORT` | `127.0.0.1` / `3000` | Host interface and port for the dashboard. |
| `CORTEXOPS_API_IMAGE` | `cortexops-api:local` | Use a prebuilt API image, e.g. `ghcr.io/ashishodu2023/cortexops-api:0.6.0`. |
| `CORTEXOPS_DASHBOARD_IMAGE` | `cortexops-dashboard:local` | Use a prebuilt dashboard image. |
| `VITE_API_URL` | empty | Build-time API URL baked into the dashboard bundle. `CORTEXOPS_API_URL` overrides it at runtime. |

### Evals, judge, email and alerting (optional)

| Variable | Default | Description |
|---|---|---|
| `MAX_EVAL_CASES_PER_RUN` | `500` | Upper bound on cases per server-side eval run. |
| `EVAL_TIMEOUT_SECONDS` | `300` | Timeout for a server-side eval run. |
| `OPENAI_API_KEY` | empty | Enables the LLM judge for server-side evals. |
| `RESEND_API_KEY` / `SENDGRID_API_KEY` | empty | Email delivery; email is disabled when both are empty. |
| `EMAIL_FROM` / `EMAIL_FROM_NAME` | empty | Sender address and name. |
| `CORTEXOPS_SLACK_WEBHOOK_URL` / `CORTEXOPS_ALERT_CHANNEL` | empty | Slack alerts. |
| `CORTEXOPS_WEBHOOK_URL` / `CORTEXOPS_WEBHOOK_SECRET` | empty | Generic signed webhook alerts. |

### Billing (hosted service only)

`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`,
`PAYPAL_PLAN_ID`, `PAYPAL_WEBHOOK_ID` and `PAYPAL_BASE_URL` configure the hosted getcortexops.com subscriptions.
Self-hosters leave them empty with `BILLING_ENABLED=false`. Without billing, keys get their tier from the bootstrap
service or the admin API instead of a subscription.

## TLS and reverse proxy

Terminate TLS in a reverse proxy and keep the containers bound to `127.0.0.1`. Two common layouts:

- **Two hosts**: `https://cortexops.example.com` to the dashboard (port 3000) and `https://api.cortexops.example.com`
  to the API (port 8000).
- **One host**: `https://cortexops.example.com`, with `/v1/` and `/health` going to the API and everything else to the dashboard.

Then set, in `.env`:

```bash
CORTEXOPS_API_URL=https://api.cortexops.example.com    # or https://cortexops.example.com for one host
CORS_ORIGINS=https://cortexops.example.com
FRONTEND_URL=https://cortexops.example.com
```

and run `docker compose up -d` to apply. The dashboard picks up `CORTEXOPS_API_URL` at container start, so no rebuild is needed.

Example Caddyfile (automatic HTTPS):

```
cortexops.example.com {
    reverse_proxy 127.0.0.1:3000
}
api.cortexops.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Example nginx server block for the API (repeat for the dashboard on port 3000):

```nginx
server {
    listen 443 ssl;
    server_name api.cortexops.example.com;
    ssl_certificate     /etc/letsencrypt/live/api.cortexops.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.cortexops.example.com/privkey.pem;
    client_max_body_size 10m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
```

The API rate limits and audit-logs requests by client IP. It honours `X-Forwarded-For` only when the connecting peer
matches `TRUSTED_PROXIES`, and then uses the right-most address that is not itself a trusted proxy, so a client cannot
pick its own IP by sending the header. Anything else is keyed by the peer address.

The compose default trusts the loopback and private ranges, which covers a reverse proxy on the host (Docker forwards
published ports from its bridge gateway, e.g. `172.17.0.1`) or in a container on a Docker network. Clients connecting
from public addresses with `API_BIND=0.0.0.0` cannot spoof the header, but any host on a private network that can reach
port 8000 can, so keep the port on `127.0.0.1` or narrow `TRUSTED_PROXIES` to your proxy's address. If the proxy is
elsewhere, set `TRUSTED_PROXIES` to its address. If it is not trusted, every request is limited as if it came from the
proxy (200 requests per minute in total). Use `*` only when nothing but a proxy that overwrites the header can reach the
API. When `TRUSTED_PROXIES` is not set at all, the API trusts no proxy, except on Railway, where it trusts any peer
because only Railway's edge, which overwrites `X-Forwarded-For`, reaches the service publicly.

## Upgrades

```bash
git pull                          # or check out a release tag, e.g. git checkout v0.6.0
docker compose up -d --build      # rebuilds images and recreates changed services
docker compose ps                 # all services healthy, bootstrap exited 0
```

With prebuilt images, bump `CORTEXOPS_API_IMAGE` / `CORTEXOPS_DASHBOARD_IMAGE` in `.env` and run
`docker compose pull && docker compose up -d`. Read the [changelog](../sdk/CHANGELOG.md) before upgrading across minor versions,
and [back up](#backups) first.

**Migrations.** The API creates missing tables on startup. For schema changes, images that ship database migrations
run them on API start when `RUN_MIGRATIONS=1` (the compose default); only the `api` service has it, so workers never
race the migration, and the worker starts once the API is healthy. Set `RUN_MIGRATIONS=0` to run migrations
yourself, for example with `docker compose run --rm api alembic upgrade head` in images that include Alembic.
The Helm chart can run them in a pre-upgrade Job instead (`migrations.job.enabled`).

## Backups

All state lives in PostgreSQL (traces, eval runs, keys, prompts). Redis holds only the job queue and transient results.

```bash
# Back up
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > cortexops-$(date +%F).dump

# Restore into a fresh stack
docker compose up -d postgres
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < cortexops-2026-01-01.dump
docker compose up -d
```

Schedule the backup with cron and keep copies off the host. Also keep `.env` somewhere safe: without `JWT_SECRET` and
`INTERNAL_API_KEY` you can still restore data, but sessions and admin access change. The named volumes are
`<project>_postgres_data` and `<project>_redis_data`; `docker compose down` keeps them, `docker compose down -v` deletes them.

## External database and Redis

To use a managed PostgreSQL or Redis, point the variables at it and stop the bundled service from starting:

```bash
# .env
POSTGRES_HOST=db.internal.example.com
POSTGRES_PORT=5432
POSTGRES_USER=cortexops
POSTGRES_PASSWORD=...
POSTGRES_DB=cortexops
REDIS_URL=rediss://:password@redis.internal.example.com:6379/0
CELERY_BROKER_URL=rediss://:password@redis.internal.example.com:6379/0
CELERY_RESULT_BACKEND=rediss://:password@redis.internal.example.com:6379/1
```

Then disable the bundled services with a `docker-compose.override.yml` next to `docker-compose.yml`
(Compose 2.24 or newer; it is merged automatically):

```yaml
services:
  postgres:
    profiles: ["bundled"]
  redis:
    profiles: ["bundled"]
  api:
    depends_on: !reset {}
  worker:
    depends_on: !override
      api:
        condition: service_healthy
```

`docker compose up -d` now starts only the API, worker, bootstrap and dashboard. PostgreSQL 14 or newer is recommended.

## Air-gapped installs

Build or pull the images on a connected machine, then move them across:

```bash
docker compose build
docker save cortexops-api:local cortexops-dashboard:local postgres:16-alpine redis:7-alpine | gzip > cortexops-images.tgz
# on the target host
docker load < cortexops-images.tgz
docker compose up -d --no-build
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `required variable JWT_SECRET is missing a value` | Create `.env` with `./deploy/compose/generate-env.sh`. |
| API restarts with `DATABASE_URL must be set to PostgreSQL` | `ENVIRONMENT=production` needs PostgreSQL; check the `POSTGRES_*` variables. |
| Dashboard loads but sign-in fails with a network error | `CORTEXOPS_API_URL` must be reachable from the browser and its origin listed in `CORS_ORIGINS`. |
| `bootstrap` exited 1 with HTTP 400 or 422 | Invalid or reserved `CORTEXOPS_PROJECT`, or empty `BOOTSTRAP_EMAIL`. |
| `bootstrap` exited 1 with HTTP 429 | Bootstrap rate limit; wait an hour or issue a key with the admin API. |
| Worker unhealthy | `docker compose logs worker`; check `CELERY_BROKER_URL` and that Redis is healthy. |

Logs: `docker compose logs -f api worker`. Status: `docker compose ps`.
