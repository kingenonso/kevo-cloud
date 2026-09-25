"""
M32 - KEVO Wallet Service client.

Thin wrapper around KEVO's own internal wallet/ledger service
(kevo-wallet-service, a separate Java/Spring Boot application - see
claude/kevo-language-assignment-policy.md for why the wallet is a
dedicated service rather than living inside this app). This wallet
tracks fictional/demo money only for the prototype (see
claude/kevo-wallet-funding-withdrawal-milestone-spec.md, Sections 27-28).
It is a deliberately separate system from the real, non-custodial
Escrow.com settlement path in escrow_client.py - real settlement money
never touches this wallet.

The wallet service is internal-only - never reachable from a browser -
and authenticates every call with a shared secret header rather than
KEVO's own JWT scheme, since it doesn't duplicate KEVO's auth logic.
Credentials come from environment variables (WALLET_SERVICE_URL /
KEVO_WALLET_INTERNAL_SECRET), loaded via the same load_dotenv() call
database.py already makes for the rest of KEVO's secrets.

Every wallet-changing call here (deposit, withdraw, lock_funds) takes an
idempotency_key. Callers must generate that key once per user action and
resend the SAME key on any retry - a fresh key on each retry defeats the
whole point. release_lock and capture_lock don't take one; they're
idempotent by the marketplace transaction's current state instead, so
calling either twice is always safe on its own.

A response dict's own "status" field ("FAILED", e.g. insufficient funds)
is a normal business outcome, not a transport error - _check() only
raises for actual HTTP/service failures. Callers must inspect
response["status"] themselves to react to a business-level failure.
"""

import os

import requests

DEFAULT_WALLET_SERVICE_URL = "http://localhost:8080"


def _base_url():
    return os.getenv("WALLET_SERVICE_URL", DEFAULT_WALLET_SERVICE_URL)


def _headers():
    secret = os.getenv("KEVO_WALLET_INTERNAL_SECRET")
    if not secret:
        raise RuntimeError("KEVO_WALLET_INTERNAL_SECRET must be set")
    return {
        "X-Internal-Service-Secret": secret,
        "Content-Type": "application/json",
    }


def _check(response):
    if not response.ok:
        raise RuntimeError(f"Wallet service error {response.status_code}: {response.text}")
    return response


def get_wallet(kevo_user_id: int) -> dict:
    """Fetches current balances (available/pending/locked/withdrawalPending/total) for a KEVO user."""
    response = _check(requests.get(
        f"{_base_url()}/internal/wallets/{kevo_user_id}", headers=_headers(), timeout=15
    ))
    return response.json()


def deposit(kevo_user_id: int, amount: float, currency: str, idempotency_key: str) -> dict:
    """Funds a user's wallet."""
    payload = {"amount": amount, "currency": currency, "idempotencyKey": idempotency_key}
    response = _check(requests.post(
        f"{_base_url()}/internal/wallets/{kevo_user_id}/deposits",
        json=payload, headers=_headers(), timeout=15
    ))
    return response.json()


def withdraw(kevo_user_id: int, amount: float, currency: str, bank_account_id: int, idempotency_key: str) -> dict:
    """Withdraws from a user's wallet to one of that user's own verified bank accounts (spec Section 14)."""
    payload = {
        "amount": amount,
        "currency": currency,
        "bankAccountId": bank_account_id,
        "idempotencyKey": idempotency_key,
    }
    response = _check(requests.post(
        f"{_base_url()}/internal/wallets/{kevo_user_id}/withdrawals",
        json=payload, headers=_headers(), timeout=15
    ))
    return response.json()


def add_bank_account(kevo_user_id: int, account_holder_name: str, bank_name: str, account_number: str) -> dict:
    """Adds a bank account to a user's wallet. Only a last-four stand-in and a demo provider token are ever stored - the real account number is discarded after this call."""
    payload = {
        "accountHolderName": account_holder_name,
        "bankName": bank_name,
        "accountNumber": account_number,
    }
    response = _check(requests.post(
        f"{_base_url()}/internal/wallets/{kevo_user_id}/bank-accounts",
        json=payload, headers=_headers(), timeout=15
    ))
    return response.json()


def list_bank_accounts(kevo_user_id: int) -> list:
    """Lists a user's bank accounts (masked - last four digits only, never the real account number)."""
    response = _check(requests.get(
        f"{_base_url()}/internal/wallets/{kevo_user_id}/bank-accounts",
        headers=_headers(), timeout=15
    ))
    return response.json()


def verify_bank_account(kevo_user_id: int, bank_account_id: int) -> dict:
    """Demo verification step for a bank account (spec Section 14; a real integration would replace this with micro-deposits or an instant-verification provider)."""
    response = _check(requests.post(
        f"{_base_url()}/internal/wallets/{kevo_user_id}/bank-accounts/{bank_account_id}/verify",
        headers=_headers(), timeout=15
    ))
    return response.json()


def disable_bank_account(kevo_user_id: int, bank_account_id: int) -> dict:
    """Disables a bank account so it can no longer receive withdrawals."""
    response = _check(requests.post(
        f"{_base_url()}/internal/wallets/{kevo_user_id}/bank-accounts/{bank_account_id}/disable",
        headers=_headers(), timeout=15
    ))
    return response.json()


def lock_funds(kevo_user_id: int, amount: float, currency: str, marketplace_transaction_id: int, idempotency_key: str) -> dict:
    """Locks funds in a buyer's wallet for a specific marketplace transaction. Locked funds cannot be withdrawn or locked again elsewhere."""
    payload = {
        "amount": amount,
        "currency": currency,
        "marketplaceTransactionId": marketplace_transaction_id,
        "idempotencyKey": idempotency_key,
    }
    response = _check(requests.post(
        f"{_base_url()}/internal/wallets/{kevo_user_id}/locks",
        json=payload, headers=_headers(), timeout=15
    ))
    return response.json()


def release_lock(kevo_user_id: int, marketplace_transaction_id: int) -> dict:
    """Releases a buyer's locked funds back to available - call when a deal falls through. Safe to call more than once."""
    payload = {"marketplaceTransactionId": marketplace_transaction_id}
    response = _check(requests.post(
        f"{_base_url()}/internal/wallets/{kevo_user_id}/locks/release",
        json=payload, headers=_headers(), timeout=15
    ))
    return response.json()


def capture_lock(buyer_kevo_user_id: int, marketplace_transaction_id: int, seller_kevo_user_id: int) -> dict:
    """Completes settlement: moves a buyer's locked funds into the seller's available balance. Safe to call more than once."""
    payload = {
        "marketplaceTransactionId": marketplace_transaction_id,
        "sellerKevoUserId": seller_kevo_user_id,
    }
    response = _check(requests.post(
        f"{_base_url()}/internal/wallets/{buyer_kevo_user_id}/locks/capture",
        json=payload, headers=_headers(), timeout=15
    ))
    return response.json()
