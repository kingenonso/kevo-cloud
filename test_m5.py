"""
Tests for the M5 ownership-verification fix (2026-09-11) - second of six
M1-M12 findings from the re-verification audit. Written against the REAL
~/KEVO implementation.

Finding: two inconsistent routes existed for the same real action -
PUT /ownership/{id}/verify (could verify or reject, but its response
omitted listing_id) and POST /ownership/{id}/verify (always hardcoded
"verified", could never reject, but did include listing_id).

Fix: kept PUT (it's the only one that can express both outcomes, and
matches the pattern used elsewhere - PUT /listings/{id}, PUT /users/{id}/kyc-status),
added the missing listing_id to its response, and removed POST entirely.
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

from models import Base, User as UserModel, Listing as ListingModel, OwnershipRecord
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


def make_seller(db):
    seller = UserModel(name="Seller", email=f"seller{id(object())}@example.com", role="seller")
    db.add(seller)
    db.commit()
    db.refresh(seller)
    return seller


def make_listing(db, seller):
    listing = ListingModel(
        seller_id=seller.id, company="Acme Inc", asset_type="Private Shares",
        quantity=1000, asking_price=50.0, is_transferable=True,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_ownership(db, seller, listing=None):
    ownership = OwnershipRecord(
        seller_id=seller.id,
        listing_id=listing.id if listing else None,
        company="Acme Inc", asset_type="Private Shares", quantity=1000,
    )
    db.add(ownership)
    db.commit()
    db.refresh(ownership)
    return ownership


def make_auth_headers(db):
    user = UserModel(
        name="Auth User",
        email=f"authuser{id(object())}@example.com",
        role="seller",
        account_type="admin",
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


# --- PUT /ownership/{id}/verify: core behavior preserved ---

def test_put_verify_accepts_verified_status(client, db_session):
    seller = make_seller(db_session)
    ownership = make_ownership(db_session, seller)
    headers = make_auth_headers(db_session)

    resp = client.put(
        f"/ownership/{ownership.id}/verify",
        params={"status": "verified", "verification_reference": "REF-001"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()["ownership"]
    assert body["verification_status"] == "verified"
    assert body["verification_reference"] == "REF-001"


def test_put_verify_accepts_rejected_status(client, db_session):
    seller = make_seller(db_session)
    ownership = make_ownership(db_session, seller)
    headers = make_auth_headers(db_session)

    resp = client.put(
        f"/ownership/{ownership.id}/verify",
        params={"status": "rejected", "verification_reference": "REF-002"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["ownership"]["verification_status"] == "rejected"


def test_put_verify_rejects_invalid_status(client, db_session):
    seller = make_seller(db_session)
    ownership = make_ownership(db_session, seller)
    headers = make_auth_headers(db_session)

    resp = client.put(
        f"/ownership/{ownership.id}/verify",
        params={"status": "pending", "verification_reference": "REF-003"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_put_verify_404_for_unknown_ownership(client, db_session):
    headers = make_auth_headers(db_session)
    resp = client.put(
        "/ownership/999999/verify",
        params={"status": "verified", "verification_reference": "REF-004"},
        headers=headers,
    )
    assert resp.status_code == 404


# --- The actual fix: listing_id now present in the response ---

def test_put_verify_response_includes_listing_id_when_present(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller)
    ownership = make_ownership(db_session, seller, listing=listing)
    headers = make_auth_headers(db_session)

    resp = client.put(
        f"/ownership/{ownership.id}/verify",
        params={"status": "verified", "verification_reference": "REF-005"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()["ownership"]
    assert "listing_id" in body
    assert body["listing_id"] == listing.id


def test_put_verify_response_includes_listing_id_when_null(client, db_session):
    seller = make_seller(db_session)
    ownership = make_ownership(db_session, seller, listing=None)
    headers = make_auth_headers(db_session)

    resp = client.put(
        f"/ownership/{ownership.id}/verify",
        params={"status": "verified", "verification_reference": "REF-006"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()["ownership"]
    assert "listing_id" in body
    assert body["listing_id"] is None


# --- The duplicate POST route is gone ---

def test_post_verify_route_no_longer_exists(client, db_session):
    seller = make_seller(db_session)
    ownership = make_ownership(db_session, seller)

    resp = client.post(
        f"/ownership/{ownership.id}/verify",
        params={"verification_reference": "REF-007"},
    )
    # Path still exists (PUT is registered on it) but POST is not -> 405, not 200
    assert resp.status_code == 405


def test_post_verify_can_no_longer_force_verified_without_status(client, db_session):
    seller = make_seller(db_session)
    ownership = make_ownership(db_session, seller)

    resp = client.post(f"/ownership/{ownership.id}/verify")
    assert resp.status_code == 405
    # confirm nothing was silently changed via the old hardcoded-verified path
    refreshed = db_session.query(OwnershipRecord).filter(OwnershipRecord.id == ownership.id).first()
    assert refreshed.verification_status == "pending"
