"""
Tests for Batch B Group 3 item 9 (2026-09-24): Seller Financing,
tracking-only.

KEVO never originates, funds, holds, or services this credit
arrangement -- the seller and buyer negotiate principal/rate/term
directly (same caller-supplied-terms invariant as Transaction.agreed_price)
and KEVO only records the agreement plus a generated payment schedule.
POST /seller-financing-agreements is seller-or-admin (mirrors ROFR's
"seller submits" pattern), requires the transaction be accepted or in
settlement, and auto-generates the installment schedule via ordinary
amortization math. Confirming a payment is seller-or-admin (the seller is
the one owed the money, so they attest to receiving it -- no real
integration exists to verify this independently, same posture as
Evidence/KYCFact self-submission).
"""
import os
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    Base, User as UserModel, Listing as ListingModel, Transaction,
    SellerFinancingAgreement, SellerFinancingPayment,
)
from app import app, get_db, hash_password, create_access_token


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    session = TestingSessionLocal()
    yield session
    session.close()
    app.dependency_overrides.clear()


@pytest.fixture()
def client(db_session):
    return TestClient(app)


def auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def make_user(db, suffix="1", role="buyer", account_type="participant", kyc_status="not_started"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"sfuser{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller, quantity=1000):
    listing = ListingModel(
        seller_id=seller.id, company="Acme Inc", asset_type="Private Shares",
        quantity=quantity, asking_price=50.0, is_transferable=True,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_transaction(db, listing, buyer, quantity=100, status="accepted", agreed_price=10.0):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=quantity, agreed_price=agreed_price, status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def base_payload(txn_id, **overrides):
    payload = {
        "transaction_id": txn_id,
        "principal_amount": 1200.0,
        "annual_interest_rate_pct": 0,
        "term_months": 12,
        "payment_frequency": "monthly",
        "first_payment_due_date": "2026-10-01",
    }
    payload.update(overrides)
    return payload


# --- POST /seller-financing-agreements ---

def test_seller_can_create_agreement_zero_interest_schedule_sums_to_principal(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    resp = client.post("/seller-financing-agreements", headers=auth_headers(seller), json=base_payload(txn.id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["transaction_id"] == txn.id

    payments_resp = client.get(f"/seller-financing-agreements/{body['id']}/payments", headers=auth_headers(seller))
    assert payments_resp.status_code == 200
    payments = payments_resp.json()
    assert len(payments) == 12
    assert all(p["status"] == "pending" for p in payments)
    total = sum(p["amount_due"] for p in payments)
    assert round(total, 2) == 1200.0
    assert payments[0]["due_date"] == "2026-10-01"
    assert payments[1]["due_date"] == "2026-11-01"
    assert payments[0]["installment_number"] == 1
    assert payments[-1]["installment_number"] == 12


def test_admin_can_create_agreement(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    resp = client.post("/seller-financing-agreements", headers=auth_headers(admin), json=base_payload(txn.id))
    assert resp.status_code == 200


def test_buyer_cannot_create_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    resp = client.post("/seller-financing-agreements", headers=auth_headers(buyer), json=base_payload(txn.id))
    assert resp.status_code == 403


def test_stranger_cannot_create_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    resp = client.post("/seller-financing-agreements", headers=auth_headers(stranger), json=base_payload(txn.id))
    assert resp.status_code == 403


def test_create_unauthenticated_401(client, db_session):
    resp = client.post("/seller-financing-agreements", json=base_payload(1))
    assert resp.status_code == 401


def test_create_transaction_not_found_404(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    resp = client.post("/seller-financing-agreements", headers=auth_headers(seller), json=base_payload(999999))
    assert resp.status_code == 404


def test_create_rejects_transaction_not_yet_accepted(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="interested")

    resp = client.post("/seller-financing-agreements", headers=auth_headers(seller), json=base_payload(txn.id))
    assert resp.status_code == 400


def test_create_allows_settlement_pending_transaction(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")

    resp = client.post("/seller-financing-agreements", headers=auth_headers(seller), json=base_payload(txn.id))
    assert resp.status_code == 200


def test_create_rejects_duplicate_agreement(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    first = client.post("/seller-financing-agreements", headers=auth_headers(seller), json=base_payload(txn.id))
    assert first.status_code == 200
    second = client.post("/seller-financing-agreements", headers=auth_headers(seller), json=base_payload(txn.id))
    assert second.status_code == 400


@pytest.mark.parametrize("overrides", [
    {"principal_amount": 0},
    {"principal_amount": -100},
    {"annual_interest_rate_pct": -1},
    {"term_months": 0},
    {"payment_frequency": "weekly"},
    {"payment_frequency": "quarterly", "term_months": 5},
])
def test_create_validation_rejections(client, db_session, overrides):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    resp = client.post("/seller-financing-agreements", headers=auth_headers(seller), json=base_payload(txn.id, **overrides))
    assert resp.status_code == 400


def test_quarterly_schedule_has_correct_count_and_spacing(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    resp = client.post(
        "/seller-financing-agreements", headers=auth_headers(seller),
        json=base_payload(txn.id, term_months=12, payment_frequency="quarterly")
    )
    assert resp.status_code == 200
    agreement_id = resp.json()["id"]
    payments = client.get(f"/seller-financing-agreements/{agreement_id}/payments", headers=auth_headers(seller)).json()
    assert len(payments) == 4
    assert payments[1]["due_date"] == "2027-01-01"


def test_schedule_with_interest_is_positive_and_reconciles(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    resp = client.post(
        "/seller-financing-agreements", headers=auth_headers(seller),
        json=base_payload(txn.id, principal_amount=10000.0, annual_interest_rate_pct=6.0, term_months=24)
    )
    assert resp.status_code == 200
    agreement_id = resp.json()["id"]
    payments = client.get(f"/seller-financing-agreements/{agreement_id}/payments", headers=auth_headers(seller)).json()
    assert len(payments) == 24
    assert all(p["amount_due"] > 0 for p in payments)
    # With real interest, total payments should exceed the bare principal.
    assert sum(p["amount_due"] for p in payments) > 10000.0


# --- PUT .../payments/{id}/confirm ---

def _create_agreement(client, seller, txn, **overrides):
    resp = client.post("/seller-financing-agreements", headers=auth_headers(seller), json=base_payload(txn.id, **overrides))
    assert resp.status_code == 200
    return resp.json()


def test_seller_can_confirm_payment(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = _create_agreement(client, seller, txn)
    payments = client.get(f"/seller-financing-agreements/{agreement['id']}/payments", headers=auth_headers(seller)).json()
    first_payment = payments[0]

    resp = client.put(
        f"/seller-financing-agreements/{agreement['id']}/payments/{first_payment['id']}/confirm",
        headers=auth_headers(seller)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "paid"
    assert body["paid_at"] is not None
    assert body["paid_amount"] == first_payment["amount_due"]


def test_buyer_cannot_confirm_payment_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = _create_agreement(client, seller, txn)
    payments = client.get(f"/seller-financing-agreements/{agreement['id']}/payments", headers=auth_headers(seller)).json()

    resp = client.put(
        f"/seller-financing-agreements/{agreement['id']}/payments/{payments[0]['id']}/confirm",
        headers=auth_headers(buyer)
    )
    assert resp.status_code == 403


def test_admin_can_confirm_payment(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = _create_agreement(client, seller, txn)
    payments = client.get(f"/seller-financing-agreements/{agreement['id']}/payments", headers=auth_headers(seller)).json()

    resp = client.put(
        f"/seller-financing-agreements/{agreement['id']}/payments/{payments[0]['id']}/confirm",
        headers=auth_headers(admin)
    )
    assert resp.status_code == 200


def test_cannot_confirm_already_paid_payment(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = _create_agreement(client, seller, txn)
    payments = client.get(f"/seller-financing-agreements/{agreement['id']}/payments", headers=auth_headers(seller)).json()
    payment_id = payments[0]["id"]

    first = client.put(f"/seller-financing-agreements/{agreement['id']}/payments/{payment_id}/confirm", headers=auth_headers(seller))
    assert first.status_code == 200
    second = client.put(f"/seller-financing-agreements/{agreement['id']}/payments/{payment_id}/confirm", headers=auth_headers(seller))
    assert second.status_code == 400


def test_confirming_last_payment_completes_agreement(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = _create_agreement(client, seller, txn, term_months=2, principal_amount=200.0)
    payments = client.get(f"/seller-financing-agreements/{agreement['id']}/payments", headers=auth_headers(seller)).json()
    assert len(payments) == 2

    for p in payments:
        resp = client.put(f"/seller-financing-agreements/{agreement['id']}/payments/{p['id']}/confirm", headers=auth_headers(seller))
        assert resp.status_code == 200

    final = client.get(f"/seller-financing-agreements/{agreement['id']}", headers=auth_headers(seller)).json()
    assert final["status"] == "completed"


# --- PUT .../payments/{id}/mark-late ---

def test_seller_can_mark_payment_late(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = _create_agreement(client, seller, txn)
    payments = client.get(f"/seller-financing-agreements/{agreement['id']}/payments", headers=auth_headers(seller)).json()

    resp = client.put(
        f"/seller-financing-agreements/{agreement['id']}/payments/{payments[0]['id']}/mark-late",
        headers=auth_headers(seller)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "late"


def test_cannot_mark_paid_payment_late(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = _create_agreement(client, seller, txn)
    payments = client.get(f"/seller-financing-agreements/{agreement['id']}/payments", headers=auth_headers(seller)).json()
    payment_id = payments[0]["id"]

    client.put(f"/seller-financing-agreements/{agreement['id']}/payments/{payment_id}/confirm", headers=auth_headers(seller))
    resp = client.put(f"/seller-financing-agreements/{agreement['id']}/payments/{payment_id}/mark-late", headers=auth_headers(seller))
    assert resp.status_code == 400


# --- GET scoping ---

def test_get_list_scoped_to_own_party_admin_sees_all(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3", role="buyer")
    admin = make_user(db_session, "4", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    _create_agreement(client, seller, txn)

    seller_view = client.get("/seller-financing-agreements", headers=auth_headers(seller)).json()
    buyer_view = client.get("/seller-financing-agreements", headers=auth_headers(buyer)).json()
    stranger_view = client.get("/seller-financing-agreements", headers=auth_headers(stranger)).json()
    admin_view = client.get("/seller-financing-agreements", headers=auth_headers(admin)).json()

    assert len(seller_view) == 1
    assert len(buyer_view) == 1
    assert len(stranger_view) == 0
    assert len(admin_view) == 1


def test_get_by_id_stranger_403_not_found_404(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = _create_agreement(client, seller, txn)

    ok = client.get(f"/seller-financing-agreements/{agreement['id']}", headers=auth_headers(buyer))
    assert ok.status_code == 200
    forbidden = client.get(f"/seller-financing-agreements/{agreement['id']}", headers=auth_headers(stranger))
    assert forbidden.status_code == 403
    missing = client.get("/seller-financing-agreements/999999", headers=auth_headers(seller))
    assert missing.status_code == 404


def test_get_payments_stranger_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = _create_agreement(client, seller, txn)

    resp = client.get(f"/seller-financing-agreements/{agreement['id']}/payments", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_get_unauthenticated_401(client, db_session):
    resp = client.get("/seller-financing-agreements")
    assert resp.status_code == 401


# --- Proportional share transfer (2026-09-26) ---

def test_confirming_payment_proportionally_transfers_shares(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller, quantity=100)
    txn = make_transaction(db_session, listing, buyer, quantity=100, status="accepted")
    agreement = _create_agreement(client, seller, txn, term_months=4, principal_amount=400.0)
    payments = client.get(f"/seller-financing-agreements/{agreement['id']}/payments", headers=auth_headers(seller)).json()
    assert len(payments) == 4

    resp = client.put(f"/seller-financing-agreements/{agreement['id']}/payments/{payments[0]['id']}/confirm", headers=auth_headers(seller))
    assert resp.status_code == 200
    current = client.get(f"/seller-financing-agreements/{agreement['id']}", headers=auth_headers(seller)).json()
    assert current["quantity_transferred"] == 25

    resp = client.put(f"/seller-financing-agreements/{agreement['id']}/payments/{payments[1]['id']}/confirm", headers=auth_headers(seller))
    assert resp.status_code == 200
    current = client.get(f"/seller-financing-agreements/{agreement['id']}", headers=auth_headers(seller)).json()
    assert current["quantity_transferred"] == 50


def test_confirming_final_payment_transfers_full_quantity(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller, quantity=99)
    txn = make_transaction(db_session, listing, buyer, quantity=99, status="accepted")
    agreement = _create_agreement(client, seller, txn, term_months=3, principal_amount=297.0)
    payments = client.get(f"/seller-financing-agreements/{agreement['id']}/payments", headers=auth_headers(seller)).json()

    for p in payments:
        resp = client.put(f"/seller-financing-agreements/{agreement['id']}/payments/{p['id']}/confirm", headers=auth_headers(seller))
        assert resp.status_code == 200

    final = client.get(f"/seller-financing-agreements/{agreement['id']}", headers=auth_headers(seller)).json()
    assert final["status"] == "completed"
    assert final["quantity_transferred"] == 99


def test_confirming_payment_after_default_rejected(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller, quantity=100)
    txn = make_transaction(db_session, listing, buyer, quantity=100, status="accepted")
    agreement = _create_agreement(client, seller, txn, term_months=2, principal_amount=200.0)
    payments = client.get(f"/seller-financing-agreements/{agreement['id']}/payments", headers=auth_headers(seller)).json()

    default_resp = client.put(
        f"/seller-financing-agreements/{agreement['id']}/default",
        params={"reason": "buyer stopped paying"},
        headers=auth_headers(seller)
    )
    assert default_resp.status_code == 200

    resp = client.put(f"/seller-financing-agreements/{agreement['id']}/payments/{payments[0]['id']}/confirm", headers=auth_headers(seller))
    assert resp.status_code == 400


def test_confirm_shares_transferable_blocked_while_financing_active(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller, quantity=100)
    txn = make_transaction(db_session, listing, buyer, quantity=100, status="accepted")
    settlement_resp = client.post("/settlement-records", params={"transaction_id": txn.id}, headers=auth_headers(admin))
    assert settlement_resp.status_code == 200
    settlement_id = settlement_resp.json()["id"]
    _create_agreement(client, seller, txn, term_months=2, principal_amount=200.0)

    resp = client.put(f"/settlement-records/{settlement_id}/confirm-shares-transferable", headers=auth_headers(admin))
    assert resp.status_code == 400
    assert "seller financing" in resp.json()["detail"].lower()


def test_confirming_last_payment_auto_marks_settlement_shares_transferable(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller, quantity=100)
    txn = make_transaction(db_session, listing, buyer, quantity=100, status="accepted")
    settlement_resp = client.post("/settlement-records", params={"transaction_id": txn.id}, headers=auth_headers(admin))
    settlement_id = settlement_resp.json()["id"]
    agreement = _create_agreement(client, seller, txn, term_months=1, principal_amount=100.0)
    payments = client.get(f"/seller-financing-agreements/{agreement['id']}/payments", headers=auth_headers(seller)).json()
    assert len(payments) == 1

    resp = client.put(f"/seller-financing-agreements/{agreement['id']}/payments/{payments[0]['id']}/confirm", headers=auth_headers(seller))
    assert resp.status_code == 200

    settlement = client.get(f"/settlement-records/{settlement_id}", headers=auth_headers(admin)).json()
    assert settlement["shares_confirmed_transferable"] is True
    assert settlement["shares_confirmed_transferable_at"] is not None
