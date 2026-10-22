"""
Full-gap-closure pass (Batch B, Group 5 item 21), 2026-10-22 - Sumsub
sandbox integration client for identity verification (KYC) and
sanctions/watchlist screening (AML).

Mirrors email_client.py / escrow_client.py's exact shape and discipline: a
thin wrapper around a real provider's real API, credentials from
environment variables, nothing faked, RuntimeError (not a silent no-op) if
unconfigured. Sumsub was chosen over a narrower identity-only vendor
(Onfido, Persona) because it covers both of KYCFact's seeded fact types in
one platform - "identity_verified" (document + liveness check) and
"sanctions_screening_clear" (AML/watchlist screening) - matching what M20's
data model already expects without needing two separate vendor
integrations. Sumsub's test/sandbox mode uses the same production API host
and real request-signing scheme; it's selected by using test (not live)
app credentials, not a different base URL - so swapping to a real,
verified production app later is a config change (SUMSUB_APP_TOKEN /
SUMSUB_SECRET_KEY), not a code change.

This is scaffolding only, built against sandbox/placeholder credentials
per the Batch B governing decision (claude/kevo-batch-b-full-gap-closure-
plan.md) - no real applicant has ever been created against a live account
through this client, and KYCFact rows are still entered the same
self-submit/admin-verify way M20 already built. Wiring this client's
results into KYCFact/User.kyc_status automatically is a future decision,
not made here.

Credentials come from environment variables (SUMSUB_APP_TOKEN /
SUMSUB_SECRET_KEY), loaded via the same load_dotenv() call database.py
already makes for the rest of KEVO's secrets.

Sumsub's request-signing scheme (unlike Mailgun/Escrow.com's simple
Basic-auth pattern): every request must carry X-App-Token, X-App-Access-Ts
(unix seconds), and X-App-Access-Sig - an HMAC-SHA256 digest, hex-encoded,
of (ts + method.upper() + path + raw_body), signed with the app's secret
key. Source: Sumsub's own "Basic Integration Guide" / API reference
(developers.sumsub.com), read directly before writing this client rather
than guessed.
"""

import hashlib
import hmac
import os
import time

import requests

SUMSUB_API_BASE = "https://api.sumsub.com"


def _credentials():
    app_token = os.getenv("SUMSUB_APP_TOKEN")
    secret_key = os.getenv("SUMSUB_SECRET_KEY")
    if not app_token or not secret_key:
        raise RuntimeError("SUMSUB_APP_TOKEN and SUMSUB_SECRET_KEY must be set")
    return app_token, secret_key


def _signed_headers(method: str, path: str, body: bytes) -> dict:
    app_token, secret_key = _credentials()
    ts = str(int(time.time()))
    signature_input = ts.encode() + method.upper().encode() + path.encode() + body
    signature = hmac.new(secret_key.encode(), signature_input, hashlib.sha256).hexdigest()
    return {
        "X-App-Token": app_token,
        "X-App-Access-Ts": ts,
        "X-App-Access-Sig": signature,
        "Content-Type": "application/json",
    }


def _check(response):
    if not response.ok:
        raise RuntimeError(f"Sumsub API error {response.status_code}: {response.text}")
    return response


def create_applicant(external_user_id: str, level_name: str = "basic-kyc-level",
                      email: str | None = None, first_name: str | None = None,
                      last_name: str | None = None) -> dict:
    """
    Creates a Sumsub applicant tied to a KEVO user (external_user_id should
    be the KEVO User.id, as a string). level_name selects which verification
    steps Sumsub runs (configured in the Sumsub dashboard, not here) -
    "basic-kyc-level" is Sumsub's own default identity-document + liveness
    level name. Returns the full applicant object; callers use ["id"] as
    the applicant id to store as a source_reference on a KYCFact row.
    """
    path = f"/resources/applicants?levelName={level_name}"
    info = {}
    if first_name:
        info["firstName"] = first_name
    if last_name:
        info["lastName"] = last_name
    payload = {"externalUserId": external_user_id}
    if email:
        payload["email"] = email
    if info:
        payload["info"] = info

    import json
    body = json.dumps(payload).encode()
    response = requests.post(
        f"{SUMSUB_API_BASE}{path}",
        data=body,
        headers=_signed_headers("POST", path, body),
        timeout=15,
    )
    return _check(response).json()


def get_applicant_status(applicant_id: str) -> dict:
    """
    Fetches an applicant's current review status (e.g. init / pending /
    completed) directly from Sumsub - this is the verification *workflow*
    state, separate from the pass/fail verdict returned by
    get_applicant_review_result().
    """
    path = f"/resources/applicants/{applicant_id}/status"
    response = requests.get(
        f"{SUMSUB_API_BASE}{path}",
        headers=_signed_headers("GET", path, b""),
        timeout=15,
    )
    return _check(response).json()


def get_applicant_review_result(applicant_id: str) -> dict:
    """
    Fetches the full applicant record, including Sumsub's review result
    (GREEN/RED verdict and reject reasons if any) and, where the configured
    level includes it, AML/watchlist (sanctions, PEP, adverse media)
    screening hits. This is the call whose result should ultimately inform
    a KYCFact's "identity_verified" / "sanctions_screening_clear" rows,
    once that automatic wiring is designed - not done by this client itself.
    """
    path = f"/resources/applicants/{applicant_id}/one"
    response = requests.get(
        f"{SUMSUB_API_BASE}{path}",
        headers=_signed_headers("GET", path, b""),
        timeout=15,
    )
    return _check(response).json()


def generate_access_token(external_user_id: str, level_name: str = "basic-kyc-level") -> dict:
    """
    Generates a short-lived access token for Sumsub's own client-side
    verification SDK/WebSDK - this is what a future frontend would use to
    let a user complete document upload and liveness check directly in
    their browser, without KEVO's backend ever handling the raw ID
    document images itself. Not yet consumed anywhere in KEVO's frontend.
    """
    path = f"/resources/accessTokens?userId={external_user_id}&levelName={level_name}"
    response = requests.post(
        f"{SUMSUB_API_BASE}{path}",
        data=b"",
        headers=_signed_headers("POST", path, b""),
        timeout=15,
    )
    return _check(response).json()
