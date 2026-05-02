from __future__ import annotations

import json
import logging
import os
import uuid

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import generate_api_key, get_current_key_info
from ..tiers import TierInfo
from ..db import get_db
from ..models.records import ApiKey, Project

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/billing", tags=["billing"])

STRIPE_SECRET_KEY    = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID      = os.getenv("STRIPE_PRICE_ID", "")
FRONTEND_URL         = os.getenv("FRONTEND_URL", "https://getcortexops.com")


def get_stripe():
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe not configured.")
    stripe.api_key = STRIPE_SECRET_KEY
    return stripe


class CheckoutRequest(BaseModel):
    project: str
    email: str
    seats: int = 1

    @field_validator("seats")
    @classmethod
    def validate_seats(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError("seats must be between 1 and 100")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or len(v) > 254:
            raise ValueError("Invalid email address")
        return v

class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


@router.post("/checkout", response_model=CheckoutResponse, responses={
    401: {"description": "Invalid or missing API key"},
    403: {"description": "Forbidden — insufficient scope or project mismatch"},
    429: {"description": "Rate limit exceeded"},
    500: {"description": "Internal server error"},
})
async def create_checkout(body: CheckoutRequest):
    s = get_stripe()
    if not STRIPE_PRICE_ID:
        raise HTTPException(status_code=503, detail="STRIPE_PRICE_ID not configured.")
    session = s.checkout.Session.create(
        mode="subscription",
        customer_email=body.email,
        line_items=[{"price": STRIPE_PRICE_ID, "quantity": body.seats}],
        metadata={"project": body.project, "email": body.email, "seats": str(body.seats)},
        subscription_data={
            "metadata": {"project": body.project, "email": body.email},
            "trial_period_days": 14,
        },
        success_url=f"{FRONTEND_URL}/?checkout=success&session_id={{CHECKOUT_SESSION_ID}}&project={body.project}",
        cancel_url=f"{FRONTEND_URL}/#pricing",
        allow_promotion_codes=False,
    )
    return CheckoutResponse(checkout_url=session.url, session_id=session.id)


@router.post("/webhook/stripe", responses={
    400: {"description": "Invalid webhook payload or signature"},
    500: {"description": "Internal server error"},
})
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    s = get_stripe()
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")
    if STRIPE_WEBHOOK_SECRET:
        try:
            event = s.Webhook.construct_event(body, sig, STRIPE_WEBHOOK_SECRET)
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid webhook signature")
    else:
        event = json.loads(body)

    etype = event["type"]
    logger.info(f"Stripe event: {etype}")

    if etype == "checkout.session.completed":
        sess = event["data"]["object"]
        # Stripe SDK v15 returns StripeObject — use getattr, not .get()
        raw_meta = getattr(sess, "metadata", None)
        meta = getattr(raw_meta, "_data", None) or {}
        sess_id = getattr(sess, "id", "") or ""
        project = meta.get("project", f"stripe-{sess_id[:8]}")
        email_addr = meta.get("email", "") or ""
        await _provision(db, project, email_addr, sess_id)

    elif etype == "customer.subscription.deleted":
        sub = event["data"]["object"]
        raw_meta = getattr(sub, "metadata", None)
        meta = getattr(raw_meta, "_data", None) or {}
        logger.info(f"Subscription cancelled: {meta.get('project', '')}")

    elif etype == "invoice.payment_failed":
        inv = event["data"]["object"]
        customer = getattr(inv, "customer", "") or ""
        logger.warning(f"Payment failed: {customer}")

    return {"status": "ok", "event": etype}



async def _send_key_email(email: str, project: str, raw_key: str) -> None:
    """
    Send the API key to the customer by email.
    Uses httpx to call a transactional email service.
    Configure SMTP or use SendGrid/Resend via SENDGRID_API_KEY or RESEND_API_KEY env vars.
    Falls back to logging if no email service is configured.
    """
    sendgrid_key = os.getenv("SENDGRID_API_KEY")
    resend_key   = os.getenv("RESEND_API_KEY")
    sendgrid_key = os.getenv("SENDGRID_API_KEY")
    logger.info(f"Email send: resend_configured={bool(resend_key)} sendgrid_configured={bool(sendgrid_key)}")

    subject = "Your CortexOps Pro API key"
    body = f"""Welcome to CortexOps Pro!

Your API key for project '{project}':

  {raw_key}

Add it to your environment:

  export CORTEXOPS_API_KEY={raw_key}
  export CORTEXOPS_PROJECT={project}

Or run the CLI login flow:

  pip install cortexops
  cortexops login

Then use without any key argument:

  from cortexops import CortexTracer
  tracer = CortexTracer(project="{project}")  # key auto-loaded

Dashboard: https://app.getcortexops.com
Docs:      https://docs.getcortexops.com

Keep this key safe — it is shown only once.

— Ashish @ CortexOps
ashish@getcortexops.com
"""

    if resend_key:
        try:
            import httpx
            r = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
                json={
                    "from": "CortexOps <ashish@getcortexops.com>",
                    "to": [email],
                    "subject": subject,
                    "text": body,
                },
                timeout=10.0,
            )
            if r.status_code == 200:
                logger.info(f"Key email sent via Resend to {email}")
                return
            logger.warning(f"Resend failed: {r.status_code} {r.text}")
        except Exception as e:
            logger.warning(f"Resend error: {e}")

    elif sendgrid_key:
        try:
            import httpx
            r = httpx.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {sendgrid_key}", "Content-Type": "application/json"},
                json={
                    "personalizations": [{"to": [{"email": email}]}],
                    "from": {"email": "ashish@getcortexops.com", "name": "CortexOps"},
                    "subject": subject,
                    "content": [{"type": "text/plain", "value": body}],
                },
                timeout=10.0,
            )
            if r.status_code in (200, 202):
                logger.info(f"Key email sent via SendGrid to {email}")
                return
            logger.warning(f"SendGrid failed: {r.status_code}")
        except Exception as e:
            logger.warning(f"SendGrid error: {e}")

    # Fallback — log the key so it can be manually retrieved from Railway logs
    logger.info(f"EMAIL_FALLBACK to={email} project={project} key={raw_key[:12]}...")

async def _provision(db, project_name, email, ref):
    # Idempotency — check if a pro key already exists for this project from this Stripe ref
    existing = await db.execute(
        select(ApiKey).where(
            ApiKey.project == project_name,
            ApiKey.name == "pro",
            ApiKey.tier == "pro",
            ApiKey.is_active,
        )
    )
    if existing.scalars().first():
        logger.info(f"Pro key already exists for project={project_name} — skipping provision")
        return None

    r = await db.execute(select(Project).where(Project.name == project_name))
    proj = r.scalar_one_or_none()
    if not proj:
        proj = Project(name=project_name, description=f"Stripe {ref}")
        db.add(proj)
        await db.flush()
    raw_key, hashed = generate_api_key()
    db.add(ApiKey(id=str(uuid.uuid4()), project=project_name, name=f"pro-{ref[:8]}", tier="pro", key_hash=hashed, is_active=True))
    await db.commit()
    logger.info(f"Provisioned key for project={project_name} email={email}")
    # Send email directly — await so it runs in the same event loop context
    await _send_key_email(email, project_name, raw_key)
    return raw_key


@router.get("/session/{session_id}", responses={
    401: {"description": "Invalid or missing API key"},
    403: {"description": "Forbidden — insufficient scope or project mismatch"},
    429: {"description": "Rate limit exceeded"},
    500: {"description": "Internal server error"},
})
async def get_session(
    session_id: str,
    tier_info: TierInfo = Depends(get_current_key_info),
):
    s = get_stripe()
    sess = s.checkout.Session.retrieve(session_id)
    return {
        "status": sess.status,
        "payment_status": sess.payment_status,
        "customer_email": sess.customer_details.email if sess.customer_details else None,
        "project": getattr(getattr(sess, "metadata", None), "_data", {}).get("project"),
    }


class PortalRequest(BaseModel):
    customer_id: str

@router.post("/portal", responses={
    401: {"description": "Invalid or missing API key"},
    402: {"description": "Pro subscription required"},
    403: {"description": "Forbidden — insufficient scope or project mismatch"},
    429: {"description": "Rate limit exceeded"},
    500: {"description": "Internal server error"},
})
async def create_portal(
    body: PortalRequest,
    tier_info: TierInfo = Depends(get_current_key_info),
):
    """Create Stripe billing portal session. Requires Pro API key."""
    if not tier_info.is_pro:
        raise HTTPException(status_code=403, detail="Pro subscription required to access billing portal")
    s = get_stripe()
    sess = s.billing_portal.Session.create(
        customer=body.customer_id,
        return_url=f"{FRONTEND_URL}/#pricing",
    )
    return {"portal_url": sess.url}


# ══════════════════════════════════════════════════════════════════
# PAYPAL INTEGRATION
# Account owner: wife's PayPal Business account (H-4 EAD authorized)
# ══════════════════════════════════════════════════════════════════

import httpx

PAYPAL_CLIENT_ID     = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_PLAN_ID       = os.getenv("PAYPAL_PLAN_ID", "")          # Monthly Pro subscription plan
PAYPAL_WEBHOOK_ID    = os.getenv("PAYPAL_WEBHOOK_ID", "")       # For webhook verification
PAYPAL_BASE_URL      = os.getenv("PAYPAL_BASE_URL", "https://api-m.paypal.com")  # sandbox: api-m.sandbox.paypal.com


async def get_paypal_access_token() -> str:
    """Get OAuth2 access token from PayPal."""
    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="PayPal not configured.")
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{PAYPAL_BASE_URL}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
            headers={"Accept": "application/json"},
            timeout=10.0,
        )
    if r.status_code != 200:
        logger.error("PayPal token error: %s", r.text)
        raise HTTPException(status_code=503, detail="PayPal authentication failed.")
    return r.json()["access_token"]


# ── Schemas ──────────────────────────────────────────────────────

class PayPalCheckoutRequest(BaseModel):
    project: str
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or len(v) > 254:
            raise ValueError("Invalid email address")
        return v

    @field_validator("project")
    @classmethod
    def validate_project(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2 or len(v) > 64:
            raise ValueError("project must be 2-64 characters")
        return v


class PayPalCheckoutResponse(BaseModel):
    approval_url: str
    subscription_id: str


class PayPalWebhookVerification(BaseModel):
    auth_algo: str
    cert_url: str
    transmission_id: str
    transmission_sig: str
    transmission_time: str
    webhook_id: str
    webhook_event: dict


# ── Routes ───────────────────────────────────────────────────────

@router.post(
    "/paypal/checkout",
    response_model=PayPalCheckoutResponse,
    responses={
        401: {"description": "Invalid or missing API key"},
        503: {"description": "PayPal not configured"},
        500: {"description": "Internal server error"},
    },
    summary="Create PayPal subscription checkout",
)
async def create_paypal_checkout(body: PayPalCheckoutRequest):
    """
    Create a PayPal subscription. Returns approval_url to redirect user to PayPal.
    On approval, PayPal redirects to FRONTEND_URL/?paypal=success&sub={subscription_id}.
    """
    if not PAYPAL_PLAN_ID:
        raise HTTPException(status_code=503, detail="PAYPAL_PLAN_ID not configured.")

    token = await get_paypal_access_token()
    idempotency_key = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"cortexops-{body.project}-{body.email}"))

    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{PAYPAL_BASE_URL}/v1/billing/subscriptions",
            json={
                "plan_id": PAYPAL_PLAN_ID,
                "subscriber": {
                    "email_address": body.email,
                },
                "custom_id": body.project,           # stored on subscription for webhook use
                "application_context": {
                    "brand_name": "CortexOps",
                    "locale": "en-US",
                    "shipping_preference": "NO_SHIPPING",
                    "user_action": "SUBSCRIBE_NOW",
                    "payment_method": {
                        "payer_selected": "PAYPAL",
                        "payee_preferred": "IMMEDIATE_PAYMENT_REQUIRED",
                    },
                    "return_url": f"{FRONTEND_URL}/?paypal=success&project={body.project}",
                    "cancel_url": f"{FRONTEND_URL}/#pricing",
                },
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "PayPal-Request-Id": idempotency_key,   # idempotency — safe to retry
            },
            timeout=15.0,
        )

    if r.status_code not in (200, 201):
        logger.error("PayPal subscription create error %s: %s", r.status_code, r.text)
        raise HTTPException(status_code=503, detail="PayPal subscription creation failed.")

    data = r.json()
    subscription_id = data.get("id", "")

    # Extract approval URL for redirect
    approval_url = next(
        (link["href"] for link in data.get("links", []) if link.get("rel") == "approve"),
        None,
    )
    if not approval_url:
        raise HTTPException(status_code=503, detail="PayPal did not return approval URL.")

    logger.info("PayPal subscription created: %s for project=%s", subscription_id, body.project)
    return PayPalCheckoutResponse(approval_url=approval_url, subscription_id=subscription_id)


@router.post(
    "/paypal/webhook",
    responses={
        400: {"description": "Invalid webhook payload or signature"},
        500: {"description": "Internal server error"},
    },
    summary="Handle PayPal subscription webhooks",
)
async def paypal_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Handle PayPal subscription lifecycle webhooks.
    Events handled:
      - BILLING.SUBSCRIPTION.ACTIVATED  → provision Pro API key
      - BILLING.SUBSCRIPTION.CANCELLED  → downgrade to free
      - BILLING.SUBSCRIPTION.SUSPENDED  → downgrade to free
      - PAYMENT.SALE.COMPLETED          → log successful payment
    """
    body_bytes = await request.body()

    # ── Verify webhook signature ──────────────────────────────────
    if PAYPAL_WEBHOOK_ID:
        token = await get_paypal_access_token()
        async with httpx.AsyncClient() as client:
            verify_r = await client.post(
                f"{PAYPAL_BASE_URL}/v1/notifications/verify-webhook-signature",
                json={
                    "auth_algo":         request.headers.get("PAYPAL-AUTH-ALGO", ""),
                    "cert_url":          request.headers.get("PAYPAL-CERT-URL", ""),
                    "transmission_id":   request.headers.get("PAYPAL-TRANSMISSION-ID", ""),
                    "transmission_sig":  request.headers.get("PAYPAL-TRANSMISSION-SIG", ""),
                    "transmission_time": request.headers.get("PAYPAL-TRANSMISSION-TIME", ""),
                    "webhook_id":        PAYPAL_WEBHOOK_ID,
                    "webhook_event":     body_bytes.decode(),
                },
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=10.0,
            )
        if verify_r.status_code != 200 or verify_r.json().get("verification_status") != "SUCCESS":
            logger.warning("PayPal webhook signature verification failed")
            raise HTTPException(status_code=400, detail="Invalid PayPal webhook signature.")
    else:
        logger.warning("PAYPAL_WEBHOOK_ID not set — skipping signature verification (dev mode)")

    try:
        event = body_bytes.decode()
        import json as _json
        payload = _json.loads(event)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    event_type   = payload.get("event_type", "")
    resource     = payload.get("resource", {})
    subscription_id = resource.get("id", "")
    project      = resource.get("custom_id", "") or resource.get("custom", "")

    logger.info("PayPal webhook: event=%s subscription=%s project=%s", event_type, subscription_id, project)

    # ── Handle events ─────────────────────────────────────────────
    if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
        # Provision Pro API key for this project
        if not project:
            logger.error("PayPal ACTIVATED webhook missing custom_id/project")
            return {"status": "skipped", "reason": "no project identifier"}

        # Idempotency: skip if Pro key already exists for this subscription
        existing = await db.scalar(
            select(ApiKey).where(
                ApiKey.project == project,
                ApiKey.tier == "pro",
                ApiKey.is_active == True,
            )
        )
        if existing:
            logger.info("PayPal: Pro key already exists for project=%s — skipping", project)
            return {"status": "already_provisioned"}

        # Generate Pro API key
        from ..auth import generate_api_key as _gen_key
        raw_key, hashed = _gen_key()

        api_key = ApiKey(
            id=str(uuid.uuid4()),
            project=project,
            name=f"paypal-pro-{subscription_id[:12]}",
            key_hash=hashed,
            tier="pro",
            scope="read_write",
            is_active=True,
        )
        db.add(api_key)
        await db.commit()

        logger.info(
            "PayPal Pro key provisioned: project=%s subscription=%s key=%s",
            project, subscription_id, raw_key[:16] + "..."
        )
        # NOTE: email the raw_key to the user via Resend/SendGrid
        # TODO: call send_pro_welcome_email(project=project, raw_key=raw_key)

    elif event_type in ("BILLING.SUBSCRIPTION.CANCELLED", "BILLING.SUBSCRIPTION.SUSPENDED"):
        # Downgrade Pro keys to free for this project
        result = await db.execute(
            select(ApiKey).where(
                ApiKey.project == project,
                ApiKey.tier == "pro",
                ApiKey.is_active == True,
            )
        )
        keys = result.scalars().all()
        for key in keys:
            key.tier = "free"
        await db.commit()
        logger.info("PayPal: downgraded %d Pro keys to free for project=%s", len(keys), project)

    elif event_type == "PAYMENT.SALE.COMPLETED":
        amount = resource.get("amount", {}).get("total", "unknown")
        currency = resource.get("amount", {}).get("currency", "USD")
        logger.info("PayPal payment received: %s %s for subscription=%s", amount, currency, subscription_id)

    return {"status": "processed", "event_type": event_type}