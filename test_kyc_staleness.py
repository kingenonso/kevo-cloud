"""
Tests for KYC re-verification staleness (2026-10-26).

No regulator (FinCEN, FCA, FATF) sets a fixed KYC re-verification
period - it's an explicit risk-based judgment call. These tests check
KEVO's own INDUSTRY-PRACTICE convention (KYC_REVERIFICATION_WINDOW_DAYS
in app.py: high ~12mo / medium ~24mo / low ~36mo, with "high" as the
fail-safe default when no risk tier has been assigned), not any
regulatory requirement.

Covers:
  - kyc_is_current() as a pure function across tiers/boundaries.
  - require_verified_user() (the money/listing-moving hard gate) now
    also rejecting a verified-but-stale account, via POST /listings.
  - PUT /users/{id}/kyc-status setting/clearing kyc_verified_at and
    accepting/validating the optional risk_tier parameter.
"""
import os
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, User as UserModel
from app import (
    app,
    get_db,
    hash_password,
    create_access_token,
    kyc_is_current,
    KYC_REVERIFICATION_WINDOW_DAYS,
    DEFAULT_KYC_RISK_TIER,
)


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


def make_user(db, suffix="1", role="buyer", account_type="participant",
              kyc_status="verified", kyc_verified_at=None, kyc_risk_tier=None):
    user = UserModel(
        name=f"User {suffix}",
        email=f"kycstale{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        hashed_password=hash_password("testpass123"),
        kyc_status=kyc_status,
        kyc_verified_at=kyc_verified_at,
        kyc_risk_tier=kyc_risk_tier,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def listing_payload(seller_id, **overrides):
    payload = {
        "seller_id": seller_id,
        "company": "Acme Secondary Co",
        "asset_type": "common_stock",
        "quantity": 100,
        "asking_price": 50.0,
    }
    payload.update(overrides)
    return payload


# --- kyc_is_current(): pure-function behavior ---

class _FakeUser:
    def __init__(self, kyc_verified_at, kyc_risk_tier=None):
        self.kyc_verified_at = kyc_verified_at
        self.kyc_risk_tier = kyc_risk_tier


def test_kyc_is_current_true_when_timestamp_not_tracked():
    # No kyc_verified_at on file means staleness isn't being tracked for
    # this account (e.g. verified before this feature existed) - same
    # opt-in posture as ComplianceRule.fact_validity_days being null.
    # Not an automatic fail.
    assert kyc_is_current(_FakeUser(kyc_verified_at=None)) is True


def test_kyc_is_current_true_just_verified_default_tier():
    user = _FakeUser(kyc_verified_at=datetime.utcnow())
    assert kyc_is_current(user) is True


def test_kyc_is_current_false_past_default_high_window():
    # Default tier is "high" (~365 days) when none is assigned.
    assert DEFAULT_KYC_RISK_TIER == "high"
    stale_at = datetime.utcnow() - timedelta(days=KYC_REVERIFICATION_WINDOW_DAYS["high"] + 1)
    user = _FakeUser(kyc_verified_at=stale_at)
    assert kyc_is_current(user) is False


def test_kyc_is_current_true_within_low_tier_window():
    # 400 days ago is stale for "high" but fine for "low" (~1095 days).
    verified_at = datetime.utcnow() - timedelta(days=400)
    user = _FakeUser(kyc_verified_at=verified_at, kyc_risk_tier="low")
    assert kyc_is_current(user) is True


def test_kyc_is_current_false_past_low_tier_window():
    verified_at = datetime.utcnow() - timedelta(days=KYC_REVERIFICATION_WINDOW_DAYS["low"] + 1)
    user = _FakeUser(kyc_verified_at=verified_at, kyc_risk_tier="low")
    assert kyc_is_current(user) is False


def test_kyc_is_current_respects_medium_tier_boundary():
    just_inside = datetime.utcnow() - timedelta(days=KYC_REVERIFICATION_WINDOW_DAYS["medium"] - 1)
    just_outside = datetime.utcnow() - timedelta(days=KYC_REVERIFICATION_WINDOW_DAYS["medium"] + 1)
    assert kyc_is_current(_FakeUser(kyc_verified_at=just_inside, kyc_risk_tier="medium")) is True
    assert kyc_is_current(_FakeUser(kyc_verified_at=just_outside, kyc_risk_tier="medium")) is False


def test_kyc_is_current_unknown_tier_falls_back_to_default():
    # A risk tier value that isn't one of the three known keys (e.g. bad
    # data) should fall back to the fail-safe default, not KeyError.
    stale_for_high = datetime.utcnow() - timedelta(days=KYC_REVERIFICATION_WINDOW_DAYS["high"] + 1)
    user = _FakeUser(kyc_verified_at=stale_for_high, kyc_risk_tier="not-a-real-tier")
    assert kyc_is_current(user) is False


# --- require_verified_user() hard gate, exercised via POST /listings ---

def test_listing_blocked_when_kyc_not_verified(client, db_session):
    seller = make_user(db_session, "1", role="seller", kyc_status="not_started", kyc_verified_at=None)
    resp = client.post("/listings", json=listing_payload(seller.id), headers=auth_headers(seller))
    assert resp.status_code == 403
    assert "Complete KYC verification" in resp.json()["detail"]


def test_listing_allowed_when_verified_but_never_timestamped(client, db_session):
    # Grandfather case: kyc_status says verified but kyc_verified_at was
    # never recorded (e.g. predates this feature). Staleness isn't
    # tracked for this account yet, so it's allowed through on kyc_status
    # alone - not automatically treated as stale.
    seller = make_user(db_session, "1", role="seller", kyc_status="verified", kyc_verified_at=None)
    resp = client.post("/listings", json=listing_payload(seller.id), headers=auth_headers(seller))
    assert resp.status_code == 200


def test_listing_allowed_when_verified_and_current(client, db_session):
    seller = make_user(
        db_session, "1", role="seller", kyc_status="verified",
        kyc_verified_at=datetime.utcnow() - timedelta(days=5),
    )
    resp = client.post("/listings", json=listing_payload(seller.id), headers=auth_headers(seller))
    assert resp.status_code == 200


def test_listing_blocked_when_verified_but_stale_past_high_default(client, db_session):
    seller = make_user(
        db_session, "1", role="seller", kyc_status="verified",
        kyc_verified_at=datetime.utcnow() - timedelta(days=KYC_REVERIFICATION_WINDOW_DAYS["high"] + 1),
    )
    resp = client.post("/listings", json=listing_payload(seller.id), headers=auth_headers(seller))
    assert resp.status_code == 403
    assert "expired" in resp.json()["detail"]


def test_listing_allowed_when_stale_for_high_but_current_for_assigned_low_tier(client, db_session):
    seller = make_user(
        db_session, "1", role="seller", kyc_status="verified",
        kyc_verified_at=datetime.utcnow() - timedelta(days=400),
        kyc_risk_tier="low",
    )
    resp = client.post("/listings", json=listing_payload(seller.id), headers=auth_headers(seller))
    assert resp.status_code == 200


def test_admin_exempt_from_kyc_staleness(client, db_session):
    admin = make_user(db_session, "1", role="seller", account_type="admin",
                       kyc_status="not_started", kyc_verified_at=None)
    resp = client.post("/listings", json=listing_payload(admin.id), headers=auth_headers(admin))
    assert resp.status_code == 200


# --- PUT /users/{id}/kyc-status: staleness clock + risk_tier ---

def test_verifying_kyc_sets_verified_at(client, db_session):
    admin = make_user(db_session, "admin", account_type="admin")
    target = make_user(db_session, "2", kyc_status="not_started", kyc_verified_at=None)

    resp = client.put(
        f"/users/{target.id}/kyc-status",
        params={"status": "verified"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    body = resp.json()["user"]
    assert body["kyc_verified_at"] is not None

    db_session.refresh(target)
    assert target.kyc_verified_at is not None
    assert kyc_is_current(target) is True


def test_rejecting_kyc_clears_verified_at(client, db_session):
    admin = make_user(db_session, "admin", account_type="admin")
    target = make_user(db_session, "2", kyc_status="verified", kyc_verified_at=datetime.utcnow())

    resp = client.put(
        f"/users/{target.id}/kyc-status",
        params={"status": "rejected"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["kyc_verified_at"] is None

    db_session.refresh(target)
    assert target.kyc_verified_at is None


def test_setting_risk_tier_on_verify(client, db_session):
    admin = make_user(db_session, "admin", account_type="admin")
    target = make_user(db_session, "2", kyc_status="not_started", kyc_verified_at=None)

    resp = client.put(
        f"/users/{target.id}/kyc-status",
        params={"status": "verified", "risk_tier": "low"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["kyc_risk_tier"] == "low"

    db_session.refresh(target)
    assert target.kyc_risk_tier == "low"


def test_invalid_risk_tier_rejected(client, db_session):
    admin = make_user(db_session, "admin", account_type="admin")
    target = make_user(db_session, "2", kyc_status="not_started", kyc_verified_at=None)

    resp = client.put(
        f"/users/{target.id}/kyc-status",
        params={"status": "verified", "risk_tier": "extremely-high"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 400


def test_omitting_risk_tier_leaves_existing_tier_unchanged(client, db_session):
    admin = make_user(db_session, "admin", account_type="admin")
    target = make_user(
        db_session, "2", kyc_status="verified",
        kyc_verified_at=datetime.utcnow() - timedelta(days=400), kyc_risk_tier="low",
    )

    # Re-verify without passing risk_tier - should refresh the timestamp
    # but not disturb the existing "low" tier.
    resp = client.put(
        f"/users/{target.id}/kyc-status",
        params={"status": "verified"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["kyc_risk_tier"] == "low"
