"""
M26E - Escrow.com sandbox integration client.

Thin wrapper around the Escrow.com Partner API (sandbox). KEVO uses this
purely to hold/release money for a settlement - it never holds client
funds itself. KEVO's own data (shares_confirmed_transferable, recorded by
an admin) decides when a release countdown starts; Escrow.com's own
webhook confirms when money actually moves, in both directions (received
and disbursed).

Escrow.com restricts the final "accept" action (the one that instantly
disburses funds) to the buyer's own login - a partner cannot trigger it
via the API. Instead, KEVO marks the item shipped and received on behalf
of both parties (both partner-permitted actions), which starts a short
inspection-period countdown; Escrow.com auto-releases funds once it
lapses, with no manual click required on either side.

All requests use HTTP Basic auth (email + API key), matching Escrow.com's
documented auth scheme. Credentials come from environment variables
(ESCROW_EMAIL / ESCROW_API_KEY), loaded via the same load_dotenv() call
database.py already makes for the rest of KEVO's secrets.
"""

import os

import requests

ESCROW_API_BASE = "https://api.escrow-sandbox.com/2017-09-01"


def _auth():
    email = os.getenv("ESCROW_EMAIL")
    api_key = os.getenv("ESCROW_API_KEY")
    if not email or not api_key:
        raise RuntimeError("ESCROW_EMAIL and ESCROW_API_KEY must be set")
    return (email, api_key)


def _check(response):
    if not response.ok:
        raise RuntimeError(f"Escrow.com API error {response.status_code}: {response.text}")
    return response


def create_transaction(
    buyer_email: str,
    seller_email: str,
    amount: float,
    currency: str,
    description: str,
    inspection_period_seconds: int = 86400,
) -> dict:
    """
    Creates a real transaction on Escrow.com between the given buyer and
    seller. Returns the full transaction object Escrow.com sends back -
    callers use ["id"] as the transaction id to store as
    escrow_provider_reference.
    """
    payload = {
        "parties": [
            {"role": "buyer", "customer": buyer_email, "initiator": True},
            {"role": "seller", "customer": seller_email},
        ],
        "currency": currency.lower(),
        "description": description,
        "items": [
            {
                "title": description,
                "description": description,
                "type": "general_merchandise",
                "inspection_period": inspection_period_seconds,
                "quantity": 1,
                "schedule": [
                    {
                        "amount": float(amount),
                        "payer_customer": buyer_email,
                        "beneficiary_customer": seller_email,
                    }
                ],
            }
        ],
    }
    response = _check(requests.post(
        f"{ESCROW_API_BASE}/transaction", json=payload, auth=_auth(), timeout=15
    ))
    return response.json()


def get_transaction(transaction_id: int) -> dict:
    """Fetches the current state of a transaction directly from Escrow.com."""
    response = _check(requests.get(
        f"{ESCROW_API_BASE}/transaction/{transaction_id}", auth=_auth(), timeout=15
    ))
    return response.json()


def agree_as_customer(transaction_id: int, customer_email: str) -> dict:
    """
    Marks the given customer as having agreed to the transaction terms, on
    their behalf - a partner-permitted action. KEVO only calls this once a
    transaction has already reached "accepted" status inside KEVO itself,
    so both sides' real agreement already exists; this just carries it
    over to Escrow.com's own records.
    """
    response = requests.patch(
        f"{ESCROW_API_BASE}/transaction/{transaction_id}",
        json={"action": "agree"},
        auth=_auth(),
        headers={"As-Customer": customer_email},
        timeout=15,
    )
    return _check(response).json()


def mark_shipped(transaction_id: int, seller_email: str) -> dict:
    """Marks the item shipped by the seller, on their behalf."""
    response = requests.patch(
        f"{ESCROW_API_BASE}/transaction/{transaction_id}",
        json={"action": "ship"},
        auth=_auth(),
        headers={"As-Customer": seller_email},
        timeout=15,
    )
    return _check(response).json()


def mark_received(transaction_id: int, buyer_email: str) -> dict:
    """
    Marks the item received by the buyer, on their behalf. This starts
    Escrow.com's inspection-period countdown; once it lapses, Escrow.com
    automatically releases funds to the seller.
    """
    response = requests.patch(
        f"{ESCROW_API_BASE}/transaction/{transaction_id}",
        json={"action": "receive"},
        auth=_auth(),
        headers={"As-Customer": buyer_email},
        timeout=15,
    )
    return _check(response).json()
