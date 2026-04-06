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
        meta = sess.get("metadata", {})
        project = meta.get("project", f"stripe-{sess['id'][:8]}")
        await _provision(db, project, meta.get("email", ""), sess["id"])

    elif etype == "customer.subscription.deleted":
        sub = event["data"]["object"]
        logger.info(f"Subscription cancelled: {sub.get('metadata', {}).get('project', '')}")

    elif etype == "invoice.payment_failed":
        inv = event["data"]["object"]
        logger.warning(f"Payment failed: {inv.get('customer')}")

    return {"status": "ok", "event": etype}


async def _provision(db, project_name, email, ref):
    r = await db.execute(select(Project).where(Project.name == project_name))
    proj = r.scalar_one_or_none()
    if not proj:
        proj = Project(name=project_name, description=f"Stripe {ref}")
        db.add(proj)
        await db.flush()
    raw_key, hashed = generate_api_key()
    db.add(ApiKey(id=str(uuid.uuid4()), project=project_name, name="pro", key_hash=hashed, is_active=True))
    await db.commit()
    logger.info(f"Provisioned key for project={project_name} email={email}")
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
