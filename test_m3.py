"""
Tests for the M3 listing-update field-drop fix (2026-09-11) - third of six
M1-M12 findings from the re-verification audit. Written against the REAL
~/KEVO implementation.

Finding: PUT /listings/{id} accepted a full ListingCreate payload but only
assigned seller_id/company/asset_type/quantity/asking_price, silently
dropping issuer_reporting_status, issuer_current_information_available,
issuer_jurisdiction, and is_transferable even though POST /listings
correctly handles all of them.

Fix: update_listing now assigns and returns all four fields, using the
exact same assignment pattern (including the is_transferable None->False
fallback) that create_listing already uses, to stay consistent rather than
invent new partial-update semantics.
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

from models import Base, User as UserModel, Listing as ListingModel
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
    auth_user = UserModel(
        name="Auth User",
        email=f"authuser{id(object())}@example.com",
        role="seller",
        hashed_password=hash_password("testpass123"),
    )
    db_session.add(auth_user)
    db_session.commit()
    db_session.refresh(auth_user)
    token = create_access_token(auth_user.id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def make_seller(db, suffix="1"):
    seller = UserModel(name="Seller", email=f"seller{suffix}@example.com", role="seller")
    db.add(seller)
    db.commit()
    db.refresh(seller)
    return seller


def make_listing(db, seller, **overrides):
    defaults = dict(
        seller_id=seller.id, company="Acme Inc", asset_type="Private Shares",
        quantity=1000, asking_price=50.0, is_transferable=False,
        issuer_jurisdiction=None, issuer_reporting_status=None,
        issuer_current_information_available=None,
    )
    defaults.update(overrides)
    listing = ListingModel(**defaults)
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def base_payload(seller_id, **overrides):
    payload = {
        "seller_id": seller_id,
        "company": "Acme Inc",
        "asset_type": "Private Shares",
        "quantity": 1000,
        "asking_price": 60.0,
    }
    payload.update(overrides)
    return payload


# --- Previously-handled fields still work (regression) ---

def test_update_still_updates_core_fields(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller)

    resp = client.put(f"/listings/{listing.id}", json=base_payload(seller.id, company="New Co", quantity=500), headers=auth_headers(seller))
    assert resp.status_code == 200
    body = resp.json()["listing"]
    assert body["company"] == "New Co"
    assert body["quantity"] == 500
    assert body["asking_price"] == 60.0


def test_update_404_for_unknown_listing(client, db_session):
    seller = make_seller(db_session)
    resp = client.put("/listings/999999", json=base_payload(seller.id))
    assert resp.status_code == 404


def test_update_403_when_attempting_to_reassign_to_unknown_user(client, db_session):
    # Under M19, update_listing no longer looks up the target seller_id at
    # all - it only checks whether the caller is trying to reassign the
    # listing away from themselves. An unknown target id is rejected the
    # same way a real-but-different user's id would be: 403, not 404.
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller)
    resp = client.put(f"/listings/{listing.id}", json=base_payload(999999), headers=auth_headers(seller))
    assert resp.status_code == 403


def test_update_403_when_attempting_to_reassign_to_another_user(client, db_session):
    # Role no longer gates this at all (M19) - the real protection is that
    # a listing's own seller cannot reassign it to a different real user
    # either, regardless of that user's role.
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller)
    buyer = UserModel(name="Buyer", email="buyer1@example.com", role="buyer")
    db_session.add(buyer)
    db_session.commit()
    db_session.refresh(buyer)

    resp = client.put(f"/listings/{listing.id}", json=base_payload(buyer.id), headers=auth_headers(seller))
    assert resp.status_code == 403


# --- The actual fix: previously-dropped fields now persist ---

def test_update_now_persists_issuer_jurisdiction(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller)

    resp = client.put(f"/listings/{listing.id}", json=base_payload(seller.id, issuer_jurisdiction="Canada"), headers=auth_headers(seller))
    assert resp.status_code == 200
    body = resp.json()["listing"]
    assert body["issuer_jurisdiction"] == "Canada"

    db_session.expire_all()
    refreshed = db_session.query(ListingModel).filter(ListingModel.id == listing.id).first()
    assert refreshed.issuer_jurisdiction == "Canada"


def test_update_now_persists_issuer_reporting_status(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller)

    resp = client.put(f"/listings/{listing.id}", json=base_payload(seller.id, issuer_reporting_status="current"), headers=auth_headers(seller))
    assert resp.status_code == 200
    assert resp.json()["listing"]["issuer_reporting_status"] == "current"


def test_update_now_persists_issuer_current_information_available(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller)

    resp = client.put(f"/listings/{listing.id}", json=base_payload(seller.id, issuer_current_information_available=True), headers=auth_headers(seller))
    assert resp.status_code == 200
    assert resp.json()["listing"]["issuer_current_information_available"] is True


def test_update_now_persists_is_transferable_true(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller, is_transferable=False)

    resp = client.put(f"/listings/{listing.id}", json=base_payload(seller.id, is_transferable=True), headers=auth_headers(seller))
    assert resp.status_code == 200
    assert resp.json()["listing"]["is_transferable"] is True

    db_session.expire_all()
    refreshed = db_session.query(ListingModel).filter(ListingModel.id == listing.id).first()
    assert refreshed.is_transferable is True


def test_update_all_four_previously_dropped_fields_together(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller)

    resp = client.put(f"/listings/{listing.id}", json=base_payload(
        seller.id,
        is_transferable=True,
        issuer_jurisdiction="United Kingdom",
        issuer_reporting_status="current",
        issuer_current_information_available=True,
    ), headers=auth_headers(seller))
    assert resp.status_code == 200
    body = resp.json()["listing"]
    assert body["is_transferable"] is True
    assert body["issuer_jurisdiction"] == "United Kingdom"
    assert body["issuer_reporting_status"] == "current"
    assert body["issuer_current_information_available"] is True


# --- Documented known behavior: is_transferable omitted -> False (mirrors create, not new) ---

def test_update_omitting_is_transferable_resets_to_false_matching_create_behavior(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller, is_transferable=True)

    # payload deliberately omits is_transferable
    resp = client.put(f"/listings/{listing.id}", json=base_payload(seller.id), headers=auth_headers(seller))
    assert resp.status_code == 200
    # This mirrors create_listing's existing None -> False fallback; documented, not a new bug.
    assert resp.json()["listing"]["is_transferable"] is False
