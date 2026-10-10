# Database migrations

The backend schema is managed with [Alembic](https://alembic.sqlalchemy.org/). Everything lives in `backend/`:

| Path | Purpose |
|---|---|
| `backend/alembic.ini` | Alembic config. No database URL here: it comes from `DATABASE_URL` via `app.config.get_settings()`. |
| `backend/migrations/env.py` | Async env (asyncpg / aiosqlite). Uses `render_as_batch` on SQLite and a Postgres advisory lock so concurrent upgrades serialize. |
| `backend/migrations/versions/` | Revisions: `0001_baseline`, `0002_uniqueness`, `0003_eval_cost`. |
| `backend/app/migrate.py` | Programmatic upgrade / schema check used at startup. |
| `backend/scripts/migrate.py` | `python scripts/migrate.py` - apply migrations and print the resulting revision. Exits non-zero on failure. |

All commands below run from `backend/` (or `/app` inside the Docker image, which contains the same files).

## How the app treats the schema at startup

`init_db()` in `backend/app/db.py` decides:

| Setting | Behaviour |
|---|---|
| `RUN_MIGRATIONS=1` | Runs `alembic upgrade head` before serving. |
| SQLite, `RUN_MIGRATIONS` unset | `Base.metadata.create_all()` - local dev and tests, unchanged from before. |
| Postgres, `RUN_MIGRATIONS` unset | Checks that the database is at the head revision and refuses to start otherwise (`SchemaNotCurrentError`). It never creates or alters tables. |

The fail-fast check is deliberate: new code must not serve requests against an old schema, and it must never silently `create_all` tables on a database Alembic does not know about.

## Dev workflow

SQLite (default `DATABASE_URL=sqlite+aiosqlite:///./cortexops.db`): nothing to do, tables are created on startup. To exercise migrations locally instead:

```bash
cd backend
DATABASE_URL=sqlite+aiosqlite:////tmp/dev.db alembic upgrade head
DATABASE_URL=sqlite+aiosqlite:////tmp/dev.db alembic current
```

Local Postgres:

```bash
cd backend
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/cortexops
alembic upgrade head          # or: RUN_MIGRATIONS=1 python ../start.py
```

`alembic -x db_url=<url> ...` overrides the URL for a single command.

## Creating a revision

1. Change the models in `backend/app/models/records.py`.
2. Generate a draft against a database that is at head:

   ```bash
   cd backend
   DATABASE_URL=sqlite+aiosqlite:////tmp/dev.db alembic upgrade head
   DATABASE_URL=sqlite+aiosqlite:////tmp/dev.db alembic revision --autogenerate -m "short description" --rev-id 0004_short_name
   ```

3. Review the file by hand. Autogenerate is a draft, not a migration:
   - Keep revision ids in the `NNNN_name` form so ordering is obvious.
   - Use `op.f(...)` names; `Base.metadata` has a naming convention that matches Postgres defaults (`<table>_pkey`, `<table>_<col>_fkey`, `<table>_<col>_key`, `ix_<table>_<col>`), so names agree between models, migrations and the existing production database.
   - Use `with op.batch_alter_table(...)` for anything that alters or drops columns, so it works on SQLite.
   - Server defaults: write `server_default=sa.func.now()` rather than the SQLite-specific text autogenerate emits.
   - Data migrations must not delete user data. If existing rows can violate a new constraint, detect it and fail with a clear message (see `0002_uniqueness`).
   - Implement `downgrade()`.
4. Verify:

   ```bash
   export DATABASE_URL=sqlite+aiosqlite:////tmp/dev.db
   alembic upgrade head
   alembic check                          # models == migrations
   alembic downgrade -1 && alembic upgrade head
   pytest -q tests/test_migrations.py
   ```

   `tests/test_migrations.py` runs in CI and fails if the models and migrations drift (it is the pytest form of `alembic check`). Set `CORTEXOPS_TEST_POSTGRES_URL=postgresql+asyncpg://.../<scratch db>` to run the same tests against Postgres. The tests drop and recreate the `public` schema of that database, so never point it at a database you care about.

5. Review the SQL that will run in production (offline mode, no connection needed; the range starts after the revision production is at):

   ```bash
   alembic -x db_url=postgresql+asyncpg://u:p@h/db upgrade 0003_eval_cost:head --sql
   ```

## Revisions

| Revision | What it does |
|---|---|
| `0001_baseline` | The schema as previously created by `create_all`. Idempotent: creates only missing tables and indexes, and refuses to continue if an existing table is missing baseline columns. Cannot be downgraded. |
| `0002_uniqueness` | Unique `(project, prompt_name, version)` on `prompt_versions`; `api_keys.provision_ref` (unique) and a partial unique index allowing one active billing-provisioned Pro key per project. |
| `0003_eval_cost` | Nullable `judge_cost_usd`, `judge_tokens_in`, `judge_tokens_out` on `eval_runs` and `case_results`. |

## Adopting Alembic on an existing database

Databases created before Alembic (production included) have every table but no `alembic_version` table. Two equivalent paths:

- **Stamp, then upgrade (recommended for production).** `alembic stamp 0001_baseline` records that the baseline already exists without touching any table; `alembic upgrade head` then applies only `0002` and `0003`.
- **Upgrade directly.** `alembic upgrade head` on an unstamped database runs the baseline, which skips every table and index that already exists, then applies `0002` and `0003`.

Either way the baseline verifies that each existing table has the baseline columns and stops with a `RuntimeError` naming the missing ones if not. Columns that exist in the database but not in the models (manual hotfixes) are not an error; `alembic check` reports them so they can be folded into a revision or dropped deliberately.

## Production rollout on Railway

The Docker image already contains `alembic.ini`, `migrations/` and `scripts/migrate.py` under `/app`. **After this release the app will not start on Postgres until the schema is at head**, so one of the two options in step 4 must be configured before (or together with) the deploy.

1. **Back up.** Take a Railway Postgres backup (or `pg_dump --format=custom "$DATABASE_URL" > pre-alembic.dump`). Note the time.
2. **Check for duplicate prompt versions.** `0002_uniqueness` refuses to add the unique index while duplicates exist:

   ```sql
   SELECT project, prompt_name, version, COUNT(*) AS copies FROM prompt_versions
   GROUP BY project, prompt_name, version HAVING COUNT(*) > 1 ORDER BY project, prompt_name, version;
   ```

   If this returns rows, either fix them by hand (e.g. bump the later copy to a free version number), or set `CORTEXOPS_RESEQUENCE_PROMPT_VERSIONS=1` for the migration run. Resequencing renumbers each affected prompt `1..n` ordered by `(version, created_at, id)` and logs every change; no row is deleted, and `parent_version_id` links are by id so they are unaffected. Callers that pinned a prompt by version number may see that number change for the affected prompts only.

   Also check for projects with more than one active Pro key (these are allowed and unaffected: only keys minted by a payment event after this release carry `provision_ref`, and the constraint only covers those).

3. **Stamp the baseline** (once, from a shell with production `DATABASE_URL`, e.g. `railway run` or a one-off container from the new image):

   ```bash
   cd /app            # or backend/ in a checkout
   alembic stamp 0001_baseline
   alembic current    # -> 0001_baseline
   ```

   Optional: `alembic upgrade 0001_baseline:head --sql` prints the exact DDL for `0002` and `0003` without running it.

4. **Choose how deploys run migrations** (Railway service settings; this repo's `Dockerfile`, `start.py` and `railway.toml` are intentionally unchanged):
   - **Pre-deploy command (preferred):** set the service's pre-deploy command to `python scripts/migrate.py` (working directory `/app`). Railway runs it once per deploy before switching traffic, and a failure aborts the deploy while the old version keeps serving.
   - **Or `RUN_MIGRATIONS=1`:** set the variable on the service; every replica upgrades on boot. Safe with several replicas because `env.py` takes a Postgres advisory lock, and a no-op when already at head. A failing migration makes the new deployment fail its health check, so the previous one stays live.

   Self-hosted equivalents: run `python scripts/migrate.py` before starting the container, or set `RUN_MIGRATIONS=1`. A one-line start-command change (`sh -c "python scripts/migrate.py && python start.py"`) is the alternative for platforms without a pre-deploy hook; it is documented here rather than changed in the `Dockerfile`.

5. **Deploy** the release.
6. **Verify:**

   ```bash
   alembic current     # -> 0003_eval_cost (head)
   alembic check       # -> No new upgrade operations detected.
   curl -fsS https://api.getcortexops.com/health
   ```

   Then ingest an eval run with the SDK and confirm `judge_cost_usd` appears on `GET /v1/evals/{run_id}`.

On Postgres every migration runs in one transaction, so a failure (for example the duplicate check) leaves the database exactly as it was.

## Rollback

- **Code only.** The new columns are nullable and the new indexes only reject genuine duplicates, so the previous release runs against a head schema. Roll back the deploy and leave the schema alone; the previous release does not check the revision.
- **Schema.**

  ```bash
  alembic downgrade 0002_uniqueness   # drops the judge cost columns (their data is lost)
  alembic downgrade 0001_baseline     # drops the uniqueness indexes and api_keys.provision_ref
  ```

  The new code refuses to start on a downgraded Postgres schema, so roll the code back first. `0001_baseline` cannot be downgraded: it would drop every table. Resequenced prompt versions are not restored by a downgrade.
- **Restore.** For anything else, restore the backup from step 1 (`pg_restore --clean --if-exists -d "$DATABASE_URL" pre-alembic.dump`) and redeploy the previous release.
