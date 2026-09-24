"""
Seller Financing Protection System (2026-09-24): security deposit/reserve
tracking, collateral/security-interest tracking, automatic payment
reminders, an outstanding-balance summary, and a transfer-block hook -
integrated with the existing default/restriction workflow.

Every money/asset fact here is either an explicit term the parties agreed
to (required_amount, restricts_transfer_until_paid, collateral
description) or an admin-attested real-world fact (funded/released),
mirroring SettlementRecord's existing discipline. KEVO never computes a
penalty, never seizes anything, and never moves money itself. Collateral
records are descriptive-only (legal_review_status starts "not_reviewed")
since actually perfecting a security interest (UCC-1 filing or a control
agreement) is a real legal act outside any software system.
"""
import os
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

from datetime import date, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    Base, User as UserModel, Listing as ListingModel, Transaction,
    SellerFinancingAgreement, SellerFinancingPayment, SellerFinancingReserve,
    SellerFinancingCollateral,
)
from app import app, get_db, hash_password, create_access_token
from datetime import datetime


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


def make_user(db, suffix="1", role="buyer", account_type="participant"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"sfpuser{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status="not_started",
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller, company="Acme Inc", asset_type="Private Shares", quantity=1000):
    listing = ListingModel(
        seller_id=seller.id, company=company, asset_type=asset_type,
        quantity=quantity, asking_price=50.0, is_transferable=True,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_transaction(db, listing, buyer, quantity=100, status="accepted", agreed_price=1000.0):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=quantity, agreed_price=agreed_price, status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def make_agreement(db, transaction, principal_amount=12000.0, term_months=12,
                    restricts_transfer_until_paid=False, status="active"):
    agreement = SellerFinancingAgreement(
        transaction_id=transaction.id,
        principal_amount=principal_amount,
        annual_interest_rate_pct=0,
        term_months=term_months,
        payment_frequency="monthly",
        first_payment_due_date=date.today() + timedelta(days=30),
        status=status,
        created_at=date.today(),
        restricts_transfer_until_paid=restricts_transfer_until_paid,
    )
    db.add(agreement)
    db.commit()
    db.refresh(agreement)
    return agreement


def make_payment(db, agreement, installment_number=1, due_date=None, amount_due=1000.0, status="pending"):
    payment = SellerFinancingPayment(
        agreement_id=agreement.id,
        installment_number=installment_number,
        due_date=due_date or (date.today() + timedelta(days=30)),
        amount_due=amount_due,
        status=status,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


# --- Reserve ---

def test_seller_can_create_reserve(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    agreement = make_agreement(db_session, txn)

    resp = client.post(
        f"/seller-financing-agreements/{agreement.id}/reserve",
        headers=auth_headers(seller), json={"required_amount": 1000.0, "notes": "one month's payment held as reserve"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_buyer_cannot_create_reserve_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    agreement = make_agreement(db_session, txn)

    resp = client.post(
        f"/seller-financing-agreements/{agreement.id}/reserve",
        headers=auth_headers(buyer), json={"required_amount": 1000.0},
    )
    assert resp.status_code == 403


def test_duplicate_reserve_rejected(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    agreement = make_agreement(db_session, txn)
    client.post(f"/seller-financing-agreements/{agreement.id}/reserve", headers=auth_headers(seller), json={"required_amount": 1000.0})

    resp = client.post(f"/seller-financing-agreements/{agreement.id}/reserve", headers=auth_headers(seller), json={"required_amount": 1000.0})
    assert resp.status_code == 403


def test_admin_can_fund_and_release_reserve(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    agreement = make_agreement(db_session, txn)
    client.post(f"/seller-financing-agreements/{agreement.id}/reserve", headers=auth_headers(seller), json={"required_amount": 1000.0})

    resp = client.put(
        f"/seller-financing-agreements/{agreement.id}/reserve/fund",
        headers=auth_headers(admin), params={"funded_reference": "escrow.com txn #555"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "funded"

    resp = client.put(
        f"/seller-financing-agreements/{agreement.id}/reserve/release",
        headers=auth_headers(admin), params={"released_to": "seller", "released_reference": "parties agreed to apply reserve to missed payment"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "released"


def test_cannot_release_unfunded_reserve(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    agreement = make_agreement(db_session, txn)
    client.post(f"/seller-financing-agreements/{agreement.id}/reserve", headers=auth_headers(seller), json={"required_amount": 1000.0})

    resp = client.put(
        f"/seller-financing-agreements/{agreement.id}/reserve/release",
        headers=auth_headers(admin), params={"released_to": "buyer", "released_reference": "x"},
    )
    assert resp.status_code == 400


# --- Collateral ---

def test_either_party_can_add_collateral(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    agreement = make_agreement(db_session, txn)

    resp = client.post(
        f"/seller-financing-agreements/{agreement.id}/collateral",
        headers=auth_headers(buyer),
        json={"description": "50 additional shares of Beta Corp held as collateral", "collateral_type": "other_securities", "estimated_value": 5000.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pledged"
    assert body["legal_review_status"] == "not_reviewed"


def test_stranger_cannot_add_collateral_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    agreement = make_agreement(db_session, txn)

    resp = client.post(
        f"/seller-financing-agreements/{agreement.id}/collateral",
        headers=auth_headers(stranger),
        json={"description": "x", "collateral_type": "other"},
    )
    assert resp.status_code == 403


def test_admin_can_update_collateral_status_and_legal_review(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    agreement = make_agreement(db_session, txn)
    create_resp = client.post(
        f"/seller-financing-agreements/{agreement.id}/collateral",
        headers=auth_headers(seller), json={"description": "vehicle title held", "collateral_type": "vehicle"},
    )
    collateral_id = create_resp.json()["id"]

    resp = client.put(
        f"/seller-financing-agreements/{agreement.id}/collateral/{collateral_id}",
        headers=auth_headers(admin),
        params={"legal_review_status": "reviewed_flagged", "legal_review_notes": "needs a state DMV lien filing to actually perfect - flagged for counsel"},
    )
    assert resp.status_code == 200
    assert resp.json()["legal_review_status"] == "reviewed_flagged"


def test_seller_cannot_update_collateral_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    agreement = make_agreement(db_session, txn)
    create_resp = client.post(
        f"/seller-financing-agreements/{agreement.id}/collateral",
        headers=auth_headers(seller), json={"description": "x", "collateral_type": "other"},
    )
    collateral_id = create_resp.json()["id"]

    resp = client.put(
        f"/seller-financing-agreements/{agreement.id}/collateral/{collateral_id}",
        headers=auth_headers(seller), params={"status": "released"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Summary endpoint
# ---------------------------------------------------------------------------

def test_summary_aggregates_payments_reserve_collateral(db_session, client):
    seller = make_user(db_session, "seller")
    buyer = make_user(db_session, "buyer")
    listing = make_listing(db_session, seller, company="SummaryCo", asset_type="Private Shares")
    txn = make_transaction(db_session, listing, buyer)

    agreement = SellerFinancingAgreement(
        transaction_id=txn.id, created_at=datetime.utcnow(), principal_amount=3000.0, annual_interest_rate_pct=0,
        term_months=3, payment_frequency="monthly",
        first_payment_due_date=date.today() + timedelta(days=30),
        status="active", restricts_transfer_until_paid=True,
    )
    db_session.add(agreement)
    db_session.commit()
    db_session.refresh(agreement)

    p1 = SellerFinancingPayment(agreement_id=agreement.id, installment_number=1,
        due_date=date.today() - timedelta(days=40), amount_due=1000.0, status="paid",
        paid_at=datetime.utcnow(), paid_amount=1000.0)
    p2 = SellerFinancingPayment(agreement_id=agreement.id, installment_number=2,
        due_date=date.today() - timedelta(days=2), amount_due=1000.0, status="pending")
    p3 = SellerFinancingPayment(agreement_id=agreement.id, installment_number=3,
        due_date=date.today() + timedelta(days=28), amount_due=1000.0, status="pending")
    db_session.add_all([p1, p2, p3])

    reserve = SellerFinancingReserve(agreement_id=agreement.id, created_at=datetime.utcnow(), required_amount=500.0,
        status="funded", funded_at=datetime.utcnow(), funded_reference="escrow-ref-1")
    db_session.add(reserve)

    collateral = SellerFinancingCollateral(agreement_id=agreement.id, created_at=datetime.utcnow(),
        description="Other securities", collateral_type="other_securities",
        estimated_value=2000.0, status="pledged", legal_review_status="not_reviewed")
    db_session.add(collateral)
    db_session.commit()

    r = client.get(f"/seller-financing-agreements/{agreement.id}/summary", headers=auth_headers(buyer))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["payments_paid"] == 1
    assert body["payments_overdue"] == 1
    assert body["payments_upcoming"] == 1
    assert body["outstanding_amount"] == 2000.0
    assert body["total_paid"] == 1000.0
    assert body["reserve"]["status"] == "funded"
    assert len(body["collateral"]) == 1
    assert body["buyer_account_blocked"] is False


# ---------------------------------------------------------------------------
# Transfer-block hook on POST /listings
# ---------------------------------------------------------------------------

def _active_restricted_agreement(db_session, txn):
    agreement = SellerFinancingAgreement(
        transaction_id=txn.id, created_at=datetime.utcnow(), principal_amount=3000.0, annual_interest_rate_pct=0,
        term_months=3, payment_frequency="monthly",
        first_payment_due_date=date.today() + timedelta(days=30),
        status="active", restricts_transfer_until_paid=True,
    )
    db_session.add(agreement)
    db_session.commit()
    db_session.refresh(agreement)
    return agreement


def test_transfer_blocked_for_same_company_while_restricted(db_session, client):
    seller = make_user(db_session, "seller")
    buyer = make_user(db_session, "buyer")
    listing = make_listing(db_session, seller, company="RestrictedCo", asset_type="Private Shares")
    txn = make_transaction(db_session, listing, buyer)
    _active_restricted_agreement(db_session, txn)

    r = client.post("/listings", headers=auth_headers(buyer), json={
        "seller_id": buyer.id, "company": "RestrictedCo", "asset_type": "Private Shares",
        "quantity": 10, "asking_price": 55.0,
    })
    assert r.status_code == 403


def test_transfer_allowed_for_different_company(db_session, client):
    seller = make_user(db_session, "seller")
    buyer = make_user(db_session, "buyer")
    listing = make_listing(db_session, seller, company="RestrictedCo2", asset_type="Private Shares")
    txn = make_transaction(db_session, listing, buyer)
    _active_restricted_agreement(db_session, txn)

    r = client.post("/listings", headers=auth_headers(buyer), json={
        "seller_id": buyer.id, "company": "SomeOtherCo", "asset_type": "Private Shares",
        "quantity": 10, "asking_price": 55.0,
    })
    assert r.status_code == 200, r.text


def test_transfer_allowed_once_agreement_resolved(db_session, client):
    seller = make_user(db_session, "seller")
    buyer = make_user(db_session, "buyer")
    listing = make_listing(db_session, seller, company="ResolvedCo", asset_type="Private Shares")
    txn = make_transaction(db_session, listing, buyer)
    agreement = _active_restricted_agreement(db_session, txn)
    agreement.status = "resolved"
    db_session.commit()

    r = client.post("/listings", headers=auth_headers(buyer), json={
        "seller_id": buyer.id, "company": "ResolvedCo", "asset_type": "Private Shares",
        "quantity": 10, "asking_price": 55.0,
    })
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Reminder scan: authorization
# ---------------------------------------------------------------------------

def test_reminder_run_requires_admin(db_session, client):
    buyer = make_user(db_session, "buyer")
    r = client.post("/seller-financing-agreements/reminders/run", headers=auth_headers(buyer))
    assert r.status_code == 403


def test_reminder_run_requires_auth(db_session, client):
    r = client.post("/seller-financing-agreements/reminders/run")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Reminder scan: behavior
# ---------------------------------------------------------------------------

def test_reminder_scan_sends_upcoming_reminder_once(db_session, client):
    admin = make_user(db_session, "admin", account_type="admin")
    seller = make_user(db_session, "seller")
    buyer = make_user(db_session, "buyer")
    listing = make_listing(db_session, seller, company="ReminderCo1", asset_type="Private Shares")
    txn = make_transaction(db_session, listing, buyer)
    agreement = SellerFinancingAgreement(
        transaction_id=txn.id, created_at=datetime.utcnow(), principal_amount=1000.0, annual_interest_rate_pct=0,
        term_months=1, payment_frequency="monthly",
        first_payment_due_date=date.today() + timedelta(days=2), status="active",
    )
    db_session.add(agreement)
    db_session.commit()
    db_session.refresh(agreement)
    payment = SellerFinancingPayment(agreement_id=agreement.id, installment_number=1,
        due_date=date.today() + timedelta(days=2), amount_due=1000.0, status="pending")
    db_session.add(payment)
    db_session.commit()

    with patch("app.email_client.send_email") as mock_send:
        r1 = client.post("/seller-financing-agreements/reminders/run", headers=auth_headers(admin))
        assert r1.status_code == 200, r1.text
        first_calls = mock_send.call_count
        assert first_calls >= 1

        r2 = client.post("/seller-financing-agreements/reminders/run", headers=auth_headers(admin))
        assert r2.status_code == 200, r2.text
        assert mock_send.call_count == first_calls

    db_session.refresh(payment)
    assert payment.reminder_upcoming_sent_at is not None


def test_reminder_scan_flips_overdue_and_notifies(db_session, client):
    admin = make_user(db_session, "admin", account_type="admin")
    seller = make_user(db_session, "seller")
    buyer = make_user(db_session, "buyer")
    listing = make_listing(db_session, seller, company="ReminderCo2", asset_type="Private Shares")
    txn = make_transaction(db_session, listing, buyer)
    agreement = SellerFinancingAgreement(
        transaction_id=txn.id, created_at=datetime.utcnow(), principal_amount=1000.0, annual_interest_rate_pct=0,
        term_months=1, payment_frequency="monthly",
        first_payment_due_date=date.today() - timedelta(days=2), status="active",
    )
    db_session.add(agreement)
    db_session.commit()
    db_session.refresh(agreement)
    payment = SellerFinancingPayment(agreement_id=agreement.id, installment_number=1,
        due_date=date.today() - timedelta(days=2), amount_due=1000.0, status="pending")
    db_session.add(payment)
    db_session.commit()

    with patch("app.email_client.send_email") as mock_send:
        r = client.post("/seller-financing-agreements/reminders/run", headers=auth_headers(admin))
        assert r.status_code == 200, r.text
        assert mock_send.call_count >= 1

    db_session.refresh(payment)
    assert payment.status == "late"
    assert payment.reminder_overdue_sent_at is not None


def test_reminder_scan_counts_failed_when_send_raises(db_session, client):
    admin = make_user(db_session, "admin", account_type="admin")
    seller = make_user(db_session, "seller")
    buyer = make_user(db_session, "buyer")
    listing = make_listing(db_session, seller, company="ReminderCo3", asset_type="Private Shares")
    txn = make_transaction(db_session, listing, buyer)
    agreement = SellerFinancingAgreement(
        transaction_id=txn.id, created_at=datetime.utcnow(), principal_amount=1000.0, annual_interest_rate_pct=0,
        term_months=1, payment_frequency="monthly",
        first_payment_due_date=date.today() - timedelta(days=2), status="active",
    )
    db_session.add(agreement)
    db_session.commit()
    db_session.refresh(agreement)
    payment = SellerFinancingPayment(agreement_id=agreement.id, installment_number=1,
        due_date=date.today() - timedelta(days=2), amount_due=1000.0, status="pending")
    db_session.add(payment)
    db_session.commit()

    with patch("app.email_client.send_email", side_effect=Exception("smtp down")):
        r = client.post("/seller-financing-agreements/reminders/run", headers=auth_headers(admin))
        assert r.status_code == 200, r.text
        assert r.json()["failed"] >= 1
