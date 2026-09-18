"""
Tests for M24's first slice (2026-09-18): a read-only Deal Room aggregator.
Written against the REAL ~/KEVO implementation.

GET /deal-room/transaction/{transaction_id} pulls together data that
already exists elsewhere in the API - participants, the live
assess_compliance() verdict, ownership record status, Evidence documents
linked to this specific transaction (M23), and the M17 trio (Deal Health
Score, Risk Radar, Liquidity Roadmap) - into one authorized view. No new
tables. Authorization mirrors get_transaction exactly: caller must be the
transaction's buyer, its seller, or an admin.
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
    OwnershipRecord, Evidence, LiquidityPathStep,
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
        email=f"m24user{suffix}-{id(object())}@example.com",
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


def make_ownership(db, listing, seller, verification_status="pending"):
    record = OwnershipRecord(
        seller_id=seller.id, listing_id=listing.id, company="Acme Inc",
        asset_type="Private Shares", quantity=1000,
        verification_status=verification_status,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def make_evidence(db, user, transaction=None, evidence_type="identity_document",
                   description="test evidence", verification_status="pending"):
    ev = Evidence(
        user_id=user.id,
        transaction_id=transaction.id if transaction else None,
        evidence_type=evidence_type, description=description,
        verification_status=verification_status,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


# --- Authorization boundary ---

def test_404_for_unknown_transaction(client, db_session):
    seller = make_user(db_session, "1")
    resp = client.get("/deal-room/transaction/999999", headers=auth_headers(seller))
    assert resp.status_code == 404


def test_unauthenticated_401(client, db_session):
    resp = client.get("/deal-room/transaction/1")
    assert resp.status_code == 401


def test_buyer_party_succeeds(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/deal-room/transaction/{txn.id}", headers=auth_headers(buyer))
    assert resp.status_code == 200


def test_seller_party_succeeds(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/deal-room/transaction/{txn.id}", headers=auth_headers(seller))
    assert resp.status_code == 200


def test_non_party_403(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    stranger = make_user(db_session, "3")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/deal-room/transaction/{txn.id}", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_admin_succeeds(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/deal-room/transaction/{txn.id}", headers=auth_headers(admin))
    assert resp.status_code == 200


# --- Response shape ---

def test_response_has_expected_top_level_keys(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/deal-room/transaction/{txn.id}", headers=auth_headers(buyer))
    body = resp.json()
    for key in ["transaction", "participants", "compliance", "ownership",
                "documents", "deal_health", "risk_radar", "liquidity_roadmap"]:
        assert key in body, f"missing key: {key}"


def test_participants_are_id_and_role_only_no_pii(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/deal-room/transaction/{txn.id}", headers=auth_headers(buyer))
    body = resp.json()
    assert body["participants"]["buyer"] == {"id": buyer.id, "role": buyer.role}
    assert body["participants"]["seller"] == {"id": seller.id, "role": seller.role}
    assert "email" not in body["participants"]["buyer"]
    assert "name" not in body["participants"]["buyer"]


def test_deal_health_and_risk_radar_and_roadmap_are_populated(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/deal-room/transaction/{txn.id}", headers=auth_headers(buyer))
    body = resp.json()
    assert len(body["deal_health"]["dimensions"]) == 6
    assert len(body["risk_radar"]["flags"]) == 4
    assert len(body["liquidity_roadmap"]["steps"]) == 9


# --- Ownership aggregation ---

def test_ownership_zero_records(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/deal-room/transaction/{txn.id}", headers=auth_headers(buyer))
    ownership = resp.json()["ownership"]
    assert ownership["records_on_file"] == 0
    assert ownership["all_verified"] is False


def test_ownership_all_verified(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    make_ownership(db_session, listing, seller, verification_status="verified")
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/deal-room/transaction/{txn.id}", headers=auth_headers(buyer))
    ownership = resp.json()["ownership"]
    assert ownership["records_on_file"] == 1
    assert ownership["all_verified"] is True


# --- Document scoping: only evidence linked to THIS transaction shows up ---

def test_documents_scoped_to_this_transaction_only(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    txn1 = make_transaction(db_session, listing, buyer)
    txn2 = make_transaction(db_session, listing, buyer)

    make_evidence(db_session, buyer, transaction=txn1, description="belongs to txn1")
    make_evidence(db_session, buyer, transaction=txn2, description="belongs to txn2")
    make_evidence(db_session, buyer, transaction=None, description="not linked to any transaction")

    resp = client.get(f"/deal-room/transaction/{txn1.id}", headers=auth_headers(buyer))
    documents = resp.json()["documents"]
    assert len(documents) == 1
    assert documents[0]["description"] == "belongs to txn1"


# --- No side effects: the aggregator must not persist anything ---

def test_endpoint_does_not_persist_liquidity_path_rows(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    before = db_session.query(LiquidityPathStep).count()
    resp = client.get(f"/deal-room/transaction/{txn.id}", headers=auth_headers(buyer))
    assert resp.status_code == 200
    after = db_session.query(LiquidityPathStep).count()
    assert after == before == 0
