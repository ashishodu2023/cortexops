"""Transactional email delivery (Resend first, SendGrid fallback)."""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

DEFAULT_FROM_EMAIL = "ashish@getcortexops.com"
DEFAULT_FROM_NAME = "CortexOps"


def _sender() -> tuple[str, str]:
    return (
        os.getenv("EMAIL_FROM", DEFAULT_FROM_EMAIL),
        os.getenv("EMAIL_FROM_NAME", DEFAULT_FROM_NAME),
    )


def email_configured() -> bool:
    return bool(os.getenv("RESEND_API_KEY") or os.getenv("SENDGRID_API_KEY"))


def pro_key_email(project: str, raw_key: str) -> tuple[str, str]:
    """Return (subject, plain-text body) for a newly provisioned Pro key."""
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
    return subject, body


async def _send_resend(api_key: str, to: str, subject: str, text: str) -> bool:
    from_email, from_name = _sender()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"from": f"{from_name} <{from_email}>", "to": [to], "subject": subject, "text": text},
            )
    except httpx.HTTPError as exc:
        logger.warning("Resend error: %s", type(exc).__name__)
        return False
    if r.status_code in (200, 201, 202):
        return True
    logger.warning("Resend failed: status=%s", r.status_code)
    return False


async def _send_sendgrid(api_key: str, to: str, subject: str, text: str) -> bool:
    from_email, from_name = _sender()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "personalizations": [{"to": [{"email": to}]}],
                    "from": {"email": from_email, "name": from_name},
                    "subject": subject,
                    "content": [{"type": "text/plain", "value": text}],
                },
            )
    except httpx.HTTPError as exc:
        logger.warning("SendGrid error: %s", type(exc).__name__)
        return False
    if r.status_code in (200, 202):
        return True
    logger.warning("SendGrid failed: status=%s", r.status_code)
    return False


async def send_email(to: str, subject: str, text: str) -> str | None:
    """Send a plain-text email. Returns the provider that delivered it, or None.

    Tries every configured provider in order, so a Resend outage falls back to SendGrid.
    Never logs the message body — it may contain secrets.
    """
    providers = [
        ("resend", os.getenv("RESEND_API_KEY"), _send_resend),
        ("sendgrid", os.getenv("SENDGRID_API_KEY"), _send_sendgrid),
    ]
    for name, api_key, send in providers:
        if api_key and await send(api_key, to, subject, text):
            logger.info("Email sent via %s to %s", name, to)
            return name
    return None
