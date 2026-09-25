"""
Tests for M31's Compliant-Communication Gating, 2026-09-25:
POST/GET /transactions/{transaction_id}/messages. Sending is gated by
_check_buyer_communication_eligible() (KYC + investor classification
only) - the one deliberate exception to KEVO's informational-only
posture. Written against the real ~/KEVO implementation.
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
    ComplianceRule, Message,
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
        email=f"msg{suffix}-{id(object())}@example.com",
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


def make_transaction(db, listing, buyer, quantity=100, status="interested", agreed_price=10.0):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=quantity, agreed_price=agreed_price, status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def make_classification_rule(db, rule_code="MSG-TEST-001"):
    rule = ComplianceRule(
        rule_code=rule_code,
        description="test classification requirement",
        buyer_jurisdiction=None,
        issuer_jurisdiction=None,
        asset_type="Private Shares",
        investor_classification="accredited",
        decision_if_unmet="blocked",
        fact_type="kyc_status",
        requirement="n/a",
        active=True,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


# --- POST /transactions/{transaction_id}/messages ---

def test_buyer_can_send_when_eligible(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer", kyc_status="verified")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post(
        f"/transactions/{txn.id}/messages",
        json={"body": "Hi, interested in discussing terms."},
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 200
    assert resp.json()["sender_id"] == buyer.id
    assert resp.json()["body"] == "Hi, interested in discussing terms."


def test_seller_can_send_when_buyer_eligible(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer", kyc_status="verified")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post(
        f"/transactions/{txn.id}/messages",
        json={"body": "Thanks for your interest."},
        headers=auth_headers(seller),
    )
    assert resp.status_code == 200
    assert resp.json()["sender_id"] == seller.id


def test_stranger_cannot_send_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer", kyc_status="verified")
    stranger = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post(
        f"/transactions/{txn.id}/messages",
        json={"body": "not my deal"},
        headers=auth_headers(stranger),
    )
    assert resp.status_code == 403


def test_unauthenticated_send_401(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer", kyc_status="verified")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post(f"/transactions/{txn.id}/messages", json={"body": "hi"})
    assert resp.status_code == 401


def test_send_transaction_not_found_404(client, db_session):
    buyer = make_user(db_session, "1", role="buyer", kyc_status="verified")

    resp = client.post(
        "/transactions/999999/messages",
        json={"body": "hi"},
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 404


def test_send_blocked_when_buyer_kyc_unverified(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer", kyc_status="not_started")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post(
        f"/transactions/{txn.id}/messages",
        json={"body": "hi"},
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 403
    assert "KYC" in resp.json()["detail"]
    assert db_session.query(Message).count() == 0


def test_seller_send_also_blocked_when_buyer_kyc_unverified(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer", kyc_status="not_started")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post(
        f"/transactions/{txn.id}/messages",
        json={"body": "hi"},
        headers=auth_headers(seller),
    )
    assert resp.status_code == 403


def test_send_blocked_when_investor_classification_unmet(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer", kyc_status="verified")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    make_classification_rule(db_session)

    resp = client.post(
        f"/transactions/{txn.id}/messages",
        json={"body": "hi"},
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 403
    assert "classification" in resp.json()["detail"]
    assert db_session.query(Message).count() == 0


# --- GET /transactions/{transaction_id}/messages ---

def test_party_can_read_messages(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer", kyc_status="verified")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    client.post(
        f"/transactions/{txn.id}/messages",
        json={"body": "hello"},
        headers=auth_headers(buyer),
    )

    resp = client.get(f"/transactions/{txn.id}/messages", headers=auth_headers(seller))
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["body"] == "hello"


def test_admin_can_read_messages(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer", kyc_status="verified")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/transactions/{txn.id}/messages", headers=auth_headers(admin))
    assert resp.status_code == 200


def test_stranger_cannot_read_messages_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer", kyc_status="verified")
    stranger = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/transactions/{txn.id}/messages", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_read_unauthenticated_401(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer", kyc_status="verified")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/transactions/{txn.id}/messages")
    assert resp.status_code == 401


def test_read_transaction_not_found_404(client, db_session):
    buyer = make_user(db_session, "1", role="buyer")

    resp = client.get("/transactions/999999/messages", headers=auth_headers(buyer))
    assert resp.status_code == 404
