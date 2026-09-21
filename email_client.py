"""
Full-gap-closure pass (Batch B, group 1 item 2), 2026-09-21 - Mailgun
sandbox integration client for outbound transactional email.

Mirrors escrow_client.py's exact shape and discipline: a thin wrapper
around a real provider's real API, credentials from environment
variables, nothing faked. Mailgun's free sandbox domain needs zero
domain verification and only delivers to "authorized recipients" added
in the Mailgun dashboard - the right shape for KEVO's current
pre-launch, no-real-users state. Swapping to a real, verified sending
domain later is a config change (EMAIL_DOMAIN / EMAIL_API_KEY), not a
code change.

This unlocks a genuine forgot-password flow (KEVO currently has no way
to email a reset link to a locked-out user) and any future email
notification need. Credentials come from environment variables
(EMAIL_API_KEY / EMAIL_DOMAIN / EMAIL_FROM), loaded via the same
load_dotenv() call database.py already makes for the rest of KEVO's
secrets.
"""

import os

import requests

MAILGUN_API_BASE = "https://api.mailgun.net/v3"


def _auth():
    api_key = os.getenv("EMAIL_API_KEY")
    domain = os.getenv("EMAIL_DOMAIN")
    if not api_key or not domain:
        raise RuntimeError("EMAIL_API_KEY and EMAIL_DOMAIN must be set")
    return api_key, domain


def _check(response):
    if not response.ok:
        raise RuntimeError(f"Mailgun API error {response.status_code}: {response.text}")
    return response


def send_email(to_email: str, subject: str, body_text: str) -> dict:
    """
    Sends a plain-text email via Mailgun. Raises RuntimeError if email
    isn't configured yet, or if Mailgun itself rejects the request -
    callers that need to degrade gracefully (e.g. not leaking whether an
    email address has an account) should catch this themselves rather
    than relying on this function to swallow it.
    """
    api_key, domain = _auth()
    from_address = os.getenv("EMAIL_FROM", f"KEVO <no-reply@{domain}>")

    response = requests.post(
        f"{MAILGUN_API_BASE}/{domain}/messages",
        auth=("api", api_key),
        data={
            "from": from_address,
            "to": [to_email],
            "subject": subject,
            "text": body_text,
        },
        timeout=10,
    )
    return _check(response).json()
