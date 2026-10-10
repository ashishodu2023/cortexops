# CortexOps Helm chart

Deploys the CortexOps API, Celery worker and dashboard to Kubernetes. PostgreSQL and Redis are external by default;
Bitnami subcharts can be enabled for evaluation installs.

- Chart version `0.1.0`, app version `0.6.0`, Kubernetes 1.25+, Helm 3.8+.
- Images: `ghcr.io/ashishodu2023/cortexops-api` (API and worker) and `ghcr.io/ashishodu2023/cortexops-dashboard`,
  published by the `Self-hosting` workflow on release tags. To build your own, see [Building images](#building-images).
- For Docker Compose and general configuration, see [docs/self-hosting.md](../../../docs/self-hosting.md).

## Install

The chart is installed from a checkout of the repository:

```bash
git clone https://github.com/ashishodu2023/cortexops.git && cd cortexops
helm dependency build deploy/helm/cortexops      # fetches the optional Bitnami subcharts
```

### Production: external PostgreSQL and Redis

```bash
kubectl create namespace cortexops
kubectl -n cortexops create secret generic cortexops-secrets \
  --from-literal=JWT_SECRET="$(openssl rand -hex 32)" \
  --from-literal=INTERNAL_API_KEY="$(openssl rand -hex 32)" \
  --from-literal=DATABASE_URL='postgresql+asyncpg://cortexops:PASSWORD@postgres.example.com:5432/cortexops' \
  --from-literal=REDIS_URL='redis://:PASSWORD@redis.example.com:6379/0' \
  --from-literal=CELERY_BROKER_URL='redis://:PASSWORD@redis.example.com:6379/0' \
  --from-literal=CELERY_RESULT_BACKEND='redis://:PASSWORD@redis.example.com:6379/1'

helm install cortexops deploy/helm/cortexops -n cortexops \
  --set secrets.existingSecret=cortexops-secrets \
  --set ingress.enabled=true \
  --set ingress.className=nginx \
  --set ingress.api.host=api.cortexops.example.com \
  --set ingress.dashboard.host=cortexops.example.com \
  --set 'ingress.tls[0].secretName=cortexops-tls' \
  --set 'ingress.tls[0].hosts={api.cortexops.example.com,cortexops.example.com}'
```

With `existingSecret`, the chart reads every key of that Secret as environment variables, so it must contain all
of the keys above (the worker reads `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND`, not `REDIS_URL`).
Without `existingSecret`, set `externalDatabase.url` and `externalRedis.url`; the chart then creates the Secret and
generates `JWT_SECRET` and `INTERNAL_API_KEY`, keeping them across upgrades.

### Evaluation: bundled PostgreSQL and Redis

```bash
helm install cortexops deploy/helm/cortexops -n cortexops --create-namespace \
  --set postgresql.enabled=true --set postgresql.auth.password="$(openssl rand -hex 16)" \
  --set redis.enabled=true --set redis.auth.password="$(openssl rand -hex 16)"
```

Set the subchart passwords explicitly (or use their `auth.existingSecret`) so upgrades keep working. The Bitnami
subcharts now default to `latest` image tags on Docker Hub, which are not pinned; prefer a managed database and Redis
for production, or pin `postgresql.image.*` / `redis.image.*` to images you mirror.

### First API key

`helm install` prints the commands (see `NOTES.txt`). In short:

```bash
kubectl -n cortexops port-forward svc/cortexops-api 8000:8000 &
curl -X POST http://localhost:8000/v1/keys/bootstrap -H "Content-Type: application/json" \
  -d '{"project": "my-agent", "email": "you@example.com"}'
```

The response contains `raw_key` (shown once) and `id`. Bootstrapped keys start on the free tier; lift its limits with
`POST /v1/admin/keys/<id>/upgrade` and the `INTERNAL_API_KEY` from the release Secret, as shown in the notes.

## Values

| Key | Default | Description |
|---|---|---|
| `image.repository` | `ghcr.io/ashishodu2023/cortexops-api` | API and worker image. |
| `image.tag` | chart `appVersion` | Image tag. |
| `image.pullPolicy` | `IfNotPresent` | |
| `imagePullSecrets` | `[]` | Pull secrets for all pods. |
| `serviceAccount.create` | `true` | Create a ServiceAccount (token automount is disabled on pods). |
| `serviceAccount.name` / `.annotations` | `""` / `{}` | Name override and annotations (e.g. IRSA / Workload Identity). |
| `podSecurityContext` | UID/GID 10001, `runAsNonRoot`, `RuntimeDefault` seccomp | API, worker and migration Job pods. |
| `securityContext` | read-only root FS, no privilege escalation, drop `ALL` | All CortexOps containers. |
| `config.environment` | `production` | `ENVIRONMENT`. Production requires PostgreSQL and hides `/docs`. |
| `config.debug` | `false` | `DEBUG`. |
| `config.corsOrigins` | dashboard URL | `CORS_ORIGINS`, comma-separated. |
| `config.frontendUrl` | dashboard URL | `FRONTEND_URL`. |
| `config.trustedProxies` | private ranges | `TRUSTED_PROXIES`: peers whose `X-Forwarded-For` is trusted (IPs/CIDRs, or `*`). Must cover the ingress controller pods. |
| `config.billingEnabled` | `false` | `BILLING_ENABLED`. Hosted billing; when true, production requires `PAYPAL_WEBHOOK_ID`. |
| `config.maxEvalCasesPerRun` / `config.evalTimeoutSeconds` | `500` / `300` | Server-side eval limits. |
| `config.extraEnv` | `{}` | Extra plain environment variables (map) for the API and worker. |
| `secrets.existingSecret` | `""` | Existing Secret loaded with `envFrom`; must contain `JWT_SECRET`, `INTERNAL_API_KEY`, `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`. |
| `secrets.jwtSecret` / `secrets.internalApiKey` | generated | Kept across upgrades when generated. |
| `secrets.openaiApiKey` | `""` | Enables the LLM judge for server-side evals. |
| `secrets.extraEnv` | `{}` | Extra secret variables (map), e.g. `RESEND_API_KEY`, `CORTEXOPS_SLACK_WEBHOOK_URL`, Stripe/PayPal keys. |
| `externalDatabase.url` | `""` | `DATABASE_URL` with the asyncpg driver: `postgresql+asyncpg://user:pass@host:5432/db`. |
| `externalRedis.url` | `""` | `REDIS_URL`. |
| `externalRedis.brokerUrl` / `.resultBackendUrl` | `externalRedis.url` | Celery broker and result backend. |
| `migrations.runOnStartup` | `true` | Sets `RUN_MIGRATIONS=1` on the API (images that ship migrations apply them on start). |
| `migrations.job.enabled` | `false` | Run migrations in a Helm hook Job instead; sets `RUN_MIGRATIONS=0` on the API. |
| `migrations.job.command` | `["alembic", "upgrade", "head"]` | Migration command. |
| `migrations.job.hooks` | `post-install,pre-upgrade` | Hook phases for the Job. |
| `migrations.job.backoffLimit` / `.activeDeadlineSeconds` / `.resources` | `3` / `600` / `{}` | |
| `api.replicaCount` | `1` | Use the migration Job when running more than one replica. |
| `api.command` / `api.args` | `[]` | Override the image entrypoint (default `python start.py`). |
| `api.containerPort` | `8000` | |
| `api.service.type` / `.port` / `.annotations` | `ClusterIP` / `8000` / `{}` | |
| `api.resources` | requests 100m / 256Mi, limit 512Mi | |
| `api.livenessProbe` / `.readinessProbe` / `.startupProbe` | `GET /health` | |
| `api.autoscaling.*` | disabled, 2-6 replicas, 75% CPU | HorizontalPodAutoscaler (autoscaling/v2). |
| `api.extraEnv` | `[]` | Extra env entries (list, supports `valueFrom`). |
| `api.podAnnotations` / `.podLabels` / `.nodeSelector` / `.tolerations` / `.affinity` / `.topologySpreadConstraints` | empty | Scheduling and metadata. |
| `worker.enabled` | `true` | Deploy the Celery worker. |
| `worker.replicaCount` / `.concurrency` / `.logLevel` | `1` / `4` / `info` | |
| `worker.command` | `[]` | Override the default `celery ... worker` command. |
| `worker.resources` | requests 100m / 256Mi, limit 1Gi | |
| `worker.livenessProbe` | `celery inspect ping` | |
| `worker.autoscaling.*`, `worker.extraEnv`, scheduling keys | as for `api` | |
| `dashboard.enabled` | `true` | Deploy the dashboard. |
| `dashboard.image.repository` / `.tag` / `.pullPolicy` | `ghcr.io/ashishodu2023/cortexops-dashboard` / `appVersion` / `IfNotPresent` | |
| `dashboard.apiUrl` | API ingress URL | API URL used by the browser (`CORTEXOPS_API_URL`); `http://localhost:8000` without ingress. |
| `dashboard.containerPort` | `8080` | |
| `dashboard.service.type` / `.port` / `.annotations` | `ClusterIP` / `80` / `{}` | |
| `dashboard.podSecurityContext` | UID/GID 101, `runAsNonRoot` | nginx-unprivileged user. |
| `dashboard.resources` | requests 10m / 32Mi, limit 128Mi | |
| `dashboard.livenessProbe` / `.readinessProbe` | `GET /healthz` | |
| `dashboard.autoscaling.*`, `dashboard.extraEnv`, scheduling keys | as for `api` | |
| `ingress.enabled` | `false` | |
| `ingress.className` / `.annotations` | `""` / `{}` | e.g. `nginx`, `cert-manager.io/cluster-issuer`. |
| `ingress.api.host` | `api.cortexops.example.com` | API host. |
| `ingress.dashboard.host` | `cortexops.example.com` | Dashboard host. If equal to the API host, `/v1` and `/health` route to the API. |
| `ingress.tls` | `[]` | Standard Ingress TLS entries; enables `https://` URLs in the generated config. |
| `podDisruptionBudget.enabled` | `false` | One PDB per enabled component; needs 2+ replicas to allow evictions. |
| `podDisruptionBudget.minAvailable` / `.maxUnavailable` | `1` / `null` | |
| `postgresql.enabled` | `false` | Bitnami PostgreSQL subchart; `DATABASE_URL` is wired automatically. |
| `postgresql.auth.username` / `.database` / `.password` / `.existingSecret` | `cortexops` / `cortexops` / `""` / `""` | |
| `redis.enabled` | `false` | Bitnami Redis subchart (standalone); Redis and Celery URLs are wired automatically. |
| `redis.auth.enabled` / `.password` / `.existingSecret` | `true` / `""` / `""` | |

Any other Bitnami subchart value can be set under `postgresql.` and `redis.`.

## Security notes

- Pods run as non-root with a read-only root filesystem, all capabilities dropped and the `RuntimeDefault` seccomp
  profile; writable paths are `emptyDir` volumes (`/tmp`, and nginx's config directory for the dashboard).
- The API image creates `appuser` without a fixed UID, so the chart pins UID/GID 10001 through `podSecurityContext`.
  Kubernetes cannot verify a named `USER` as non-root, which is why a numeric UID is required with `runAsNonRoot`.
- ServiceAccount tokens are not mounted; CortexOps does not call the Kubernetes API.
- Pods roll automatically when the ConfigMap or Secret inputs change (checksum annotations).
- The API honours `X-Forwarded-For` for rate limiting and audit logs only when the connecting peer is in
  `config.trustedProxies`, and then uses the right-most address that is not a trusted proxy. The default trusts the
  private ranges, which fits most pod networks; if your pod CIDR is outside them (e.g. `100.64.0.0/10`), add it.
  Any pod in a trusted range can set the header, so narrow it to the ingress controller's pod CIDR where you can.

## Building images

```bash
docker build -t registry.example.com/cortexops-api:0.6.0 .
docker build -t registry.example.com/cortexops-dashboard:0.6.0 frontend-new
docker push registry.example.com/cortexops-api:0.6.0
docker push registry.example.com/cortexops-dashboard:0.6.0

helm upgrade --install cortexops deploy/helm/cortexops -n cortexops \
  --set image.repository=registry.example.com/cortexops-api \
  --set dashboard.image.repository=registry.example.com/cortexops-dashboard \
  ...
```

## Development

```bash
helm dependency build deploy/helm/cortexops
helm lint --strict deploy/helm/cortexops
for f in "" ci/full-values.yaml ci/bundled-values.yaml; do
  helm template ci deploy/helm/cortexops ${f:+-f deploy/helm/cortexops/$f} | kubeconform -strict -summary
done
```

The `Self-hosting` workflow runs these checks and installs the chart on a kind cluster with the bundled subcharts.
