FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── deps layer (cached unless requirements change) ─────────────────────────
FROM base AS deps
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# ── SDK layer (local package) ──────────────────────────────────────────────
FROM deps AS sdk
COPY ../sdk /sdk
RUN pip install --no-deps /sdk

# ── final image ───────────────────────────────────────────────────────────
FROM sdk AS final
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
