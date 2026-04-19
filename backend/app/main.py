from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import init_db, get_db

from .observability import configure_logging, health_aggregator
from .resilience import stripe_circuit, slack_circuit, openai_circuit
from .security import RequestIDMiddleware, RateLimitMiddleware
from .routers import admin, billing, evals, keys, jwt_auth, prompts, traces

settings = get_settings()

# Configure structured logging at startup
configure_logging(settings.environment)


async def _check_db():
    """Health check: verify DB is reachable."""
    from sqlalchemy import text
    async with get_db() as session:
        await session.execute(text("SELECT 1"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Register health checks
    health_aggregator.register("database", _check_db)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Reliability infrastructure for AI agents — evaluation, observability, regression testing.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── Middleware (order matters — outermost runs first) ─────────────────────
# 1. Request ID — attach before everything
app.add_middleware(RequestIDMiddleware)

# 2. Rate limiting
app.add_middleware(RateLimitMiddleware)

# 3. CORS — must be before routers
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)

# ── Security Headers Middleware ───────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"]   = "nosniff"
    response.headers["X-Frame-Options"]           = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"]   = "default-src 'self'"
    response.headers["Referrer-Policy"]           = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"]          = "1; mode=block"
    return response

# ── Routers ───────────────────────────────────────────────────────────────
app.include_router(admin.router)
app.include_router(jwt_auth.router)
app.include_router(billing.router)
app.include_router(evals.router)
app.include_router(traces.router)
app.include_router(prompts.router)
app.include_router(keys.router)


# ── Health endpoint — enhanced with subsystem checks ─────────────────────
@app.get("/health", tags=["system"])
async def health():
    base = {"status": "ok", "version": settings.version, "environment": settings.environment}
    # Add circuit breaker states
    base["circuits"] = {
        "stripe": stripe_circuit.get_status()["state"],
        "slack":  slack_circuit.get_status()["state"],
        "openai": openai_circuit.get_status()["state"],
    }
    return base


# ── Global exception handler ──────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__},
    )