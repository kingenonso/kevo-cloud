"""
Tests for M25's second sub-piece (2026-09-25): the Due-Diligence Checklist.

Written against the REAL ~/KEVO implementation.

A structured, per-transaction checklist. Purely organizational (unlike
ROFR or the sealed-bid auction mechanism also being built under M25) - no
legal-exposure research needed. Any party to the transaction (buyer,
seller) or an admin can create or update items, mirroring the deal room's
own collaborative posture. Endpoints:

  POST /transactions/{transaction_id}/checklist-items
  PUT  /checklist-items/{item_id}
  GET  /transactions/{transaction_id}/checklist-items
"""
import os
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    Base, User as UserModel, Listing as ListingModel, Transaction,
    Evidence, DueDiligenceChecklistItem,
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
        email=f"m25checklist{suffix}-{id(object())}@example.com",
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


# --- POST /transactions/{transaction_id}/checklist-items ---

def test_create_404_for_unknown_transaction(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    resp = client.post("/transactions/999999/checklist-items", headers=auth_headers(seller), json={
        "description": "Confirm title documents",
    })
    assert resp.status_code == 404


def test_create_unauthenticated_401(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post(f"/transactions/{txn.id}/checklist-items", json={
        "description": "Confirm title documents",
    })
    assert resp.status_code == 401


def test_create_non_party_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(stranger), json={
        "description": "Confirm title documents",
    })
    assert resp.status_code == 403


def test_create_buyer_party_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(buyer), json={
        "description": "Confirm title documents",
        "source_reference": "Deal room checklist item 1",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["transaction_id"] == txn.id
    assert body["description"] == "Confirm title documents"
    assert body["status"] == "pending"
    assert body["created_by_user_id"] == buyer.id
    assert body["completed_by_user_id"] is None
    assert body["completed_at"] is None


def test_create_seller_party_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(seller), json={
        "description": "Confirm bank details for payout",
    })
    assert resp.status_code == 200
    assert resp.json()["created_by_user_id"] == seller.id


def test_create_admin_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(admin), json={
        "description": "Confirm compliance sign-off",
    })
    assert resp.status_code == 200
    assert resp.json()["created_by_user_id"] == admin.id


def test_create_with_valid_evidence_id_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    ev = make_evidence(db_session, buyer, transaction=txn)

    resp = client.post(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(buyer), json={
        "description": "Confirm ID document",
        "evidence_id": ev.id,
    })
    assert resp.status_code == 200
    assert resp.json()["evidence_id"] == ev.id


def test_create_with_unknown_evidence_id_404(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(buyer), json={
        "description": "Confirm ID document",
        "evidence_id": 999999,
    })
    assert resp.status_code == 404


# --- PUT /checklist-items/{item_id} ---

def test_update_404_for_unknown_item(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    resp = client.put("/checklist-items/999999", headers=auth_headers(seller), params={"status": "complete"})
    assert resp.status_code == 404


def test_update_non_party_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    item = DueDiligenceChecklistItem(
        transaction_id=txn.id, description="Confirm title documents",
        status="pending", created_by_user_id=buyer.id, created_at=datetime.utcnow(),
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    resp = client.put(f"/checklist-items/{item.id}", headers=auth_headers(stranger), params={"status": "complete"})
    assert resp.status_code == 403


def test_update_invalid_status_400(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    create_resp = client.post(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(buyer), json={
        "description": "Confirm title documents",
    })
    item_id = create_resp.json()["id"]

    resp = client.put(f"/checklist-items/{item_id}", headers=auth_headers(buyer), params={"status": "bogus"})
    assert resp.status_code == 400


def test_update_to_complete_sets_completed_fields(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    create_resp = client.post(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(buyer), json={
        "description": "Confirm title documents",
    })
    item_id = create_resp.json()["id"]

    resp = client.put(f"/checklist-items/{item_id}", headers=auth_headers(seller), params={"status": "complete"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "complete"
    assert body["completed_by_user_id"] == seller.id
    assert body["completed_at"] is not None


def test_update_back_to_pending_clears_completed_fields(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    create_resp = client.post(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(buyer), json={
        "description": "Confirm title documents",
    })
    item_id = create_resp.json()["id"]
    client.put(f"/checklist-items/{item_id}", headers=auth_headers(seller), params={"status": "complete"})

    resp = client.put(f"/checklist-items/{item_id}", headers=auth_headers(seller), params={"status": "pending"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["completed_by_user_id"] is None
    assert body["completed_at"] is None


def test_update_not_applicable_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    create_resp = client.post(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(buyer), json={
        "description": "Confirm title documents",
    })
    item_id = create_resp.json()["id"]

    resp = client.put(f"/checklist-items/{item_id}", headers=auth_headers(buyer), params={"status": "not_applicable"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_applicable"


def test_update_with_valid_evidence_id_attaches_it(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    ev = make_evidence(db_session, buyer, transaction=txn)

    create_resp = client.post(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(buyer), json={
        "description": "Confirm ID document",
    })
    item_id = create_resp.json()["id"]

    resp = client.put(f"/checklist-items/{item_id}", headers=auth_headers(buyer), params={
        "status": "complete", "evidence_id": ev.id,
    })
    assert resp.status_code == 200
    assert resp.json()["evidence_id"] == ev.id


def test_update_with_unknown_evidence_id_404(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    create_resp = client.post(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(buyer), json={
        "description": "Confirm ID document",
    })
    item_id = create_resp.json()["id"]

    resp = client.put(f"/checklist-items/{item_id}", headers=auth_headers(buyer), params={
        "status": "complete", "evidence_id": 999999,
    })
    assert resp.status_code == 404


def test_update_admin_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    create_resp = client.post(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(buyer), json={
        "description": "Confirm compliance sign-off",
    })
    item_id = create_resp.json()["id"]

    resp = client.put(f"/checklist-items/{item_id}", headers=auth_headers(admin), params={"status": "complete"})
    assert resp.status_code == 200
    assert resp.json()["completed_by_user_id"] == admin.id


# --- GET /transactions/{transaction_id}/checklist-items ---

def test_list_404_for_unknown_transaction(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    resp = client.get("/transactions/999999/checklist-items", headers=auth_headers(seller))
    assert resp.status_code == 404


def test_list_non_party_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_list_scoped_to_this_transaction_only(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer1 = make_user(db_session, "2", role="buyer")
    buyer2 = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)
    txn1 = make_transaction(db_session, listing, buyer1)
    txn2 = make_transaction(db_session, listing, buyer2)

    client.post(f"/transactions/{txn1.id}/checklist-items", headers=auth_headers(buyer1), json={
        "description": "Item for txn1",
    })
    client.post(f"/transactions/{txn2.id}/checklist-items", headers=auth_headers(buyer2), json={
        "description": "Item for txn2",
    })

    resp = client.get(f"/transactions/{txn1.id}/checklist-items", headers=auth_headers(buyer1))
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["description"] == "Item for txn1"


def test_list_admin_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    client.post(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(buyer), json={
        "description": "Confirm title documents",
    })

    resp = client.get(f"/transactions/{txn.id}/checklist-items", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) == 1
