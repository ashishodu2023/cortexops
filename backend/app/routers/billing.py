from __future__ import annotations

import json
import logging
import os
import uuid

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import generate_api_key
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

class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


@router.post("/checkout", response_model=CheckoutResponse)
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
        allow_promotion_codes=True,
    )
    return CheckoutResponse(checkout_url=session.url, session_id=session.id)


@router.post("/webhook/stripe")
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
        meta = dict(raw_meta) if raw_meta else {}
        sess_id = getattr(sess, "id", "") or ""
        project = meta.get("project", f"stripe-{sess_id[:8]}")
        email_addr = meta.get("email", "") or ""
        await _provision(db, project, email_addr, sess_id)

    elif etype == "customer.subscription.deleted":
        sub = event["data"]["object"]
        raw_meta = getattr(sub, "metadata", None)
        meta = dict(raw_meta) if raw_meta else {}
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
    r = await db.execute(select(Project).where(Project.name == project_name))
    proj = r.scalar_one_or_none()
    if not proj:
        proj = Project(name=project_name, description=f"Stripe {ref}")
        db.add(proj)
        await db.flush()
    raw_key, hashed = generate_api_key()
    db.add(ApiKey(id=str(uuid.uuid4()), project=project_name, name="pro", tier="pro", key_hash=hashed, is_active=True))
    await db.commit()
    logger.info(f"Provisioned key for project={project_name} email={email}")
    # Send the key by email — non-blocking
    try:
        import asyncio
        asyncio.create_task(_send_key_email(email, project_name, raw_key))
    except RuntimeError:
        # No running event loop (e.g. tests) — skip email
        pass
    return raw_key


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    s = get_stripe()
    sess = s.checkout.Session.retrieve(session_id)
    return {
        "status": sess.status,
        "payment_status": sess.payment_status,
        "customer_email": sess.customer_details.email if sess.customer_details else None,
        "project": sess.metadata.get("project"),
    }


class PortalRequest(BaseModel):
    customer_id: str

@router.post("/portal")
async def create_portal(body: PortalRequest):
    s = get_stripe()
    sess = s.billing_portal.Session.create(customer=body.customer_id, return_url=f"{FRONTEND_URL}/#pricing")
    return {"portal_url": sess.url}