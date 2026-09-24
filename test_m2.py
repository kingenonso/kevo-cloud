"""
Tests for the M2 KYC/jurisdiction fix (2026-09-11) - written against the
REAL ~/KEVO implementation, first of six M1-M12 findings from the
re-verification audit. Confirmed before this fix: UserCreate had no
jurisdiction field at all, and a repo-wide search found zero places that
ever wrote to User.kyc_status - meaning no buyer created through the real
API could ever pass M13's kyc_status=="verified" gate or its
jurisdiction-on-file gate. Real data showed all 3 real users stuck at
kyc_status='not_started', and the one user with a jurisdiction on file
could only have gotten it via a direct database write.

Fix: jurisdiction is now accepted and stored at signup (POST /users).
kyc_status is deliberately NOT settable at signup - it moves to
"verified"/"rejected" only through a new PUT /users/{id}/kyc-status
endpoint, mirroring the exact shape of the already-existing (and correct)
PUT /ownership/{id}/verify endpoint. No "pending" state, no other new
functionality, per explicit scope instruction.

Updated 2026-09-24 (Batch B, item 3/13 - "signup should have more than
just email and password"): phone_number, date_of_birth and terms_accepted
are now required at signup, and jurisdiction moved from optional to
required. test_create_user_jurisdiction_is_optional is replaced by
test_create_user_missing_jurisdiction_rejected_400, and three new tests
cover the other new required-field validation.

Runs against an isolated in-memory SQLite database, same pattern as
test_m13.py / test_m14.py / test_m15.py / test_m16.py.
"""

import os

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, User as UserModel, Listing as ListingModel
from app import app, get_db, assess_compliance, hash_password, create_access_token


# Every signup payload needs these now - spread into each test's json dict
# so each test only has to spell out the fields it actually cares about.
SIGNUP_EXTRA = {"phone_number": "+1-555-0100", "date_of_birth": "1990-01-01", "terms_accepted": True}


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
        name="Auth Test User",
        email="__test_auth_user__@kevo.local",
        role="buyer",
        account_type="admin",
        hashed_password=hash_password("testpass123"),
    )
    db_session.add(auth_user)
    db_session.commit()
    db_session.refresh(auth_user)
    token = create_access_token(auth_user.id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


# ---------------------------------------------------------------------------
# jurisdiction on signup
# ---------------------------------------------------------------------------

def test_create_user_accepts_and_stores_jurisdiction(client, db_session):
    response = client.post("/users", json={
        **SIGNUP_EXTRA,
        "name": "Jane Buyer", "email": "jane.buyer@example.com",
        "role": "buyer", "jurisdiction": "United Kingdom", "password": "testpass123",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["jurisdiction"] == "United Kingdom"

    stored = db_session.query(UserModel).filter(UserModel.email == "jane.buyer@example.com").first()
    assert stored.jurisdiction == "United Kingdom"


def test_create_user_missing_jurisdiction_rejected_400(client, db_session):
    response = client.post("/users", json={
        **SIGNUP_EXTRA,
        "name": "No Jurisdiction Yet", "email": "nojurisdiction@example.com",
        "role": "buyer", "password": "testpass123", "jurisdiction": "",
    })
    assert response.status_code == 400


def test_create_user_duplicate_email_still_rejected(client, db_session):
    client.post("/users", json={**SIGNUP_EXTRA, "name": "A", "email": "dup@example.com", "role": "buyer", "jurisdiction": "United Kingdom", "password": "testpass123"})
    response = client.post("/users", json={**SIGNUP_EXTRA, "name": "B", "email": "dup@example.com", "role": "buyer", "jurisdiction": "United Kingdom", "password": "testpass123"})
    assert response.status_code == 400


def test_create_user_invalid_role_still_rejected(client, db_session):
    response = client.post("/users", json={**SIGNUP_EXTRA, "name": "A", "email": "badrole@example.com", "role": "admin", "jurisdiction": "United Kingdom", "password": "testpass123"})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# new required signup fields (Batch B, item 3/13)
# ---------------------------------------------------------------------------

def test_create_user_without_terms_accepted_rejected_400(client, db_session):
    response = client.post("/users", json={
        **SIGNUP_EXTRA,
        "name": "No Terms", "email": "noterms@example.com", "role": "buyer",
        "jurisdiction": "United Kingdom", "password": "testpass123",
        "terms_accepted": False,
    })
    assert response.status_code == 400


def test_create_user_missing_phone_number_rejected_400(client, db_session):
    response = client.post("/users", json={
        **SIGNUP_EXTRA,
        "name": "No Phone", "email": "nophone@example.com", "role": "buyer",
        "jurisdiction": "United Kingdom", "password": "testpass123",
        "phone_number": "",
    })
    assert response.status_code == 400


def test_create_user_underage_rejected_400(client, db_session):
    ten_years_ago = date.today().replace(year=date.today().year - 10).isoformat()
    response = client.post("/users", json={
        **SIGNUP_EXTRA,
        "name": "Too Young", "email": "tooyoung@example.com", "role": "buyer",
        "jurisdiction": "United Kingdom", "password": "testpass123",
        "date_of_birth": ten_years_ago,
    })
    assert response.status_code == 400


def test_create_user_stores_phone_and_dob_and_terms_accepted_at(client, db_session):
    response = client.post("/users", json={
        **SIGNUP_EXTRA,
        "name": "Full Signup", "email": "fullsignup@example.com", "role": "buyer",
        "jurisdiction": "United Kingdom", "password": "testpass123",
    })
    assert response.status_code == 200
    body = response.json()["user"]
    assert body["phone_number"] == "+1-555-0100"
    assert body["date_of_birth"] == "1990-01-01"
    assert body["terms_accepted"] is True

    stored = db_session.query(UserModel).filter(UserModel.email == "fullsignup@example.com").first()
    assert stored.terms_accepted_at is not None


# ---------------------------------------------------------------------------
# kyc_status via the new dedicated endpoint
# ---------------------------------------------------------------------------

def test_new_user_kyc_status_defaults_not_started(client, db_session):
    client.post("/users", json={**SIGNUP_EXTRA, "name": "A", "email": "defaultkyc@example.com", "role": "buyer", "jurisdiction": "United Kingdom", "password": "testpass123"})
    stored = db_session.query(UserModel).filter(UserModel.email == "defaultkyc@example.com").first()
    assert stored.kyc_status == "not_started"


def test_kyc_status_can_be_set_to_verified(client, db_session):
    created = client.post("/users", json={**SIGNUP_EXTRA, "name": "A", "email": "verify@example.com", "role": "buyer", "jurisdiction": "United Kingdom", "password": "testpass123"}).json()
    user_id = created["user"]["id"]

    response = client.put(f"/users/{user_id}/kyc-status", params={"status": "verified"})
    assert response.status_code == 200
    assert response.json()["user"]["kyc_status"] == "verified"

    stored = db_session.query(UserModel).filter(UserModel.id == user_id).first()
    assert stored.kyc_status == "verified"


def test_kyc_status_can_be_set_to_rejected(client, db_session):
    created = client.post("/users", json={**SIGNUP_EXTRA, "name": "A", "email": "reject@example.com", "role": "buyer", "jurisdiction": "United Kingdom", "password": "testpass123"}).json()
    user_id = created["user"]["id"]

    response = client.put(f"/users/{user_id}/kyc-status", params={"status": "rejected"})
    assert response.status_code == 200
    assert response.json()["user"]["kyc_status"] == "rejected"


def test_kyc_status_rejects_invalid_value(client, db_session):
    created = client.post("/users", json={**SIGNUP_EXTRA, "name": "A", "email": "invalidkyc@example.com", "role": "buyer", "jurisdiction": "United Kingdom", "password": "testpass123"}).json()
    user_id = created["user"]["id"]

    response = client.put(f"/users/{user_id}/kyc-status", params={"status": "pending"})
    assert response.status_code == 400


def test_kyc_status_404_for_unknown_user(client, db_session):
    response = client.put("/users/999999/kyc-status", params={"status": "verified"})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# THE PAYOFF: a buyer built entirely through the real API can now clear
# M13's kyc_status and jurisdiction gates - confirmed impossible before
# this fix (there was no code path that ever wrote either field).
# ---------------------------------------------------------------------------

def test_buyer_built_through_real_api_clears_kyc_and_jurisdiction_gates(client, db_session):
    created = client.post("/users", json={
        **SIGNUP_EXTRA,
        "name": "Real Flow Buyer", "email": "realflow@example.com",
        "role": "buyer", "jurisdiction": "United Kingdom", "password": "testpass123",
    }).json()
    buyer_id = created["user"]["id"]
    client.put(f"/users/{buyer_id}/kyc-status", params={"status": "verified"})

    buyer = db_session.query(UserModel).filter(UserModel.id == buyer_id).first()
    seller = UserModel(name="Seller", email="realflow.seller@example.com", role="seller")
    db_session.add(seller)
    db_session.commit()
    db_session.refresh(seller)
    listing = ListingModel(
        seller_id=seller.id, company="Acme Inc", asset_type="Private Shares",
        quantity=1000, asking_price=80.0, is_transferable=True,
        issuer_jurisdiction="United Kingdom",
    )
    db_session.add(listing)
    db_session.commit()
    db_session.refresh(listing)

    result = assess_compliance(buyer, listing, db_session)
    # No compliance rules are seeded in this isolated test database, so the
    # real, correct outcome is "review" (nothing to check against yet) -
    # NOT "blocked" (unverified KYC) and NOT "needs_evidence" (missing
    # jurisdiction), which is what every buyer was permanently stuck at
    # before this fix, since neither field could ever be set.
    assert result["status"] == "review"
