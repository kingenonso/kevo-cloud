"""
Tests for M31's Liquidity Event Radar (admin-entered MVP), 2026-10-22
(POST/publish/retract/GET /liquidity-event-signals).

Explicitly parked since 2026-09-05 pending its own dedicated research
pass (kevo-m31-liquidity-event-radar-research.md) - this is the
resulting design, confirmed with Eze via AskUserQuestion: no fixed
digestion-delay timer (admin judgment per event), admin-entered MVP (no
live scraper). Written against the real ~/KEVO implementation, same
fixture pattern as test_liquidity_commitments.py.
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

from models import Base, User as UserModel, LiquidityEventSignal
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


def make_user(db, suffix="1", role="buyer", account_type="participant", kyc_status="verified"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"radar{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_signal(db, admin, company="Acme Inc", asset_type="Private Shares",
                 event_type="funding_round_announced", status="draft"):
    now = datetime.utcnow()
    signal = LiquidityEventSignal(
        company=company, asset_type=asset_type, event_type=event_type,
        description="Acme Inc announced a closed Series C round.",
        source_url="https://example.com/press/acme-series-c",
        source_disclosed_at=now - timedelta(days=2),
        status=status,
        published_at=now - timedelta(days=1) if status in ("published", "retracted") else None,
        created_by_admin_id=admin.id,
        created_at=now - timedelta(days=2),
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)
    return signal


VALID_PAYLOAD = {
    "company": "Acme Inc",
    "asset_type": "Private Shares",
    "event_type": "funding_round_announced",
    "description": "Acme Inc announced a closed Series C round.",
    "source_url": "https://example.com/press/acme-series-c",
    "source_disclosed_at": (datetime.utcnow() - timedelta(days=1)).isoformat(),
}


# --- POST /liquidity-event-signals ---

def test_admin_can_create_signal_as_draft(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")

    resp = client.post("/liquidity-event-signals", params=VALID_PAYLOAD, headers=auth_headers(admin))

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "draft"
    assert data["published_at"] is None
    assert data["source_url"] == VALID_PAYLOAD["source_url"]
    assert "disclaimer" in data


def test_create_signal_requires_admin(client, db_session):
    buyer = make_user(db_session, "b1")

    resp = client.post("/liquidity-event-signals", params=VALID_PAYLOAD, headers=auth_headers(buyer))

    assert resp.status_code == 403


def test_create_signal_rejects_invalid_event_type(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    payload = {**VALID_PAYLOAD, "event_type": "rumored_acquisition"}

    resp = client.post("/liquidity-event-signals", params=payload, headers=auth_headers(admin))

    assert resp.status_code == 400
    assert "event_type must be one of" in resp.json()["detail"]


def test_create_signal_rejects_empty_source_url(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    payload = {**VALID_PAYLOAD, "source_url": "   "}

    resp = client.post("/liquidity-event-signals", params=payload, headers=auth_headers(admin))

    assert resp.status_code == 400
    assert "source_url is required" in resp.json()["detail"]


def test_create_signal_rejects_future_disclosed_at(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    payload = {**VALID_PAYLOAD, "source_disclosed_at": (datetime.utcnow() + timedelta(days=1)).isoformat()}

    resp = client.post("/liquidity-event-signals", params=payload, headers=auth_headers(admin))

    assert resp.status_code == 400
    assert "cannot be in the future" in resp.json()["detail"]


@pytest.mark.parametrize("event_type", [
    "funding_round_announced", "ipo_s1_filed", "tender_offer_announced", "ma_transaction_announced",
])
def test_create_signal_accepts_every_allowed_event_type(client, db_session, event_type):
    admin = make_user(db_session, "a1", account_type="admin")
    payload = {**VALID_PAYLOAD, "event_type": event_type}

    resp = client.post("/liquidity-event-signals", params=payload, headers=auth_headers(admin))

    assert resp.status_code == 200
    assert resp.json()["event_type"] == event_type


# --- PUT /liquidity-event-signals/{id}/publish ---

def test_admin_can_publish_draft_signal(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    signal = make_signal(db_session, admin, status="draft")

    resp = client.put(f"/liquidity-event-signals/{signal.id}/publish", headers=auth_headers(admin))

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "published"
    assert data["published_at"] is not None


def test_publish_requires_admin(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    buyer = make_user(db_session, "b1")
    signal = make_signal(db_session, admin, status="draft")

    resp = client.put(f"/liquidity-event-signals/{signal.id}/publish", headers=auth_headers(buyer))

    assert resp.status_code == 403


def test_cannot_publish_already_published_signal(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    signal = make_signal(db_session, admin, status="published")

    resp = client.put(f"/liquidity-event-signals/{signal.id}/publish", headers=auth_headers(admin))

    assert resp.status_code == 400
    assert "draft" in resp.json()["detail"]


def test_publish_404_when_missing(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")

    resp = client.put("/liquidity-event-signals/999999/publish", headers=auth_headers(admin))

    assert resp.status_code == 404


# --- PUT /liquidity-event-signals/{id}/retract ---

def test_admin_can_retract_published_signal(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    signal = make_signal(db_session, admin, status="published")

    resp = client.put(
        f"/liquidity-event-signals/{signal.id}/retract",
        params={"retraction_notes": "Company issued a correction - round was not actually closed yet"},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "retracted"
    assert data["retracted_at"] is not None
    assert "correction" in data["retraction_notes"]


def test_retract_requires_admin(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    buyer = make_user(db_session, "b1")
    signal = make_signal(db_session, admin, status="published")

    resp = client.put(f"/liquidity-event-signals/{signal.id}/retract", headers=auth_headers(buyer))

    assert resp.status_code == 403


def test_cannot_retract_a_draft_signal(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    signal = make_signal(db_session, admin, status="draft")

    resp = client.put(f"/liquidity-event-signals/{signal.id}/retract", headers=auth_headers(admin))

    assert resp.status_code == 400
    assert "published" in resp.json()["detail"]


# --- GET /liquidity-event-signals (impersonal: identical for every viewer) ---

def test_non_admin_sees_only_published_signals(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    make_signal(db_session, admin, status="draft")
    make_signal(db_session, admin, status="published")
    make_signal(db_session, admin, status="retracted")
    buyer = make_user(db_session, "b1")

    resp = client.get("/liquidity-event-signals", headers=auth_headers(buyer))

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "published"


def test_two_different_non_admin_viewers_see_identical_results(client, db_session):
    """
    The deliberately impersonal design lever: GET returns the exact same
    published signals to every viewer, never filtered by a specific
    user's holdings or stated interest.
    """
    admin = make_user(db_session, "a1", account_type="admin")
    make_signal(db_session, admin, status="published")
    buyer1 = make_user(db_session, "b1")
    buyer2 = make_user(db_session, "b2")

    resp1 = client.get("/liquidity-event-signals", headers=auth_headers(buyer1))
    resp2 = client.get("/liquidity-event-signals", headers=auth_headers(buyer2))

    assert resp1.json() == resp2.json()


def test_admin_sees_drafts_and_retracted_too(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    make_signal(db_session, admin, status="draft")
    make_signal(db_session, admin, status="published")
    make_signal(db_session, admin, status="retracted")

    resp = client.get("/liquidity-event-signals", headers=auth_headers(admin))

    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_get_filters_by_company_and_asset_type(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    make_signal(db_session, admin, company="Acme Inc", status="published")
    make_signal(db_session, admin, company="Other Co", status="published")
    buyer = make_user(db_session, "b1")

    resp = client.get(
        "/liquidity-event-signals",
        params={"company": "Acme Inc", "asset_type": "Private Shares"},
        headers=auth_headers(buyer),
    )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["company"] == "Acme Inc"


# --- GET /liquidity-event-signals/{id} ---

def test_non_admin_cannot_see_draft_signal_by_id(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    signal = make_signal(db_session, admin, status="draft")
    buyer = make_user(db_session, "b1")

    resp = client.get(f"/liquidity-event-signals/{signal.id}", headers=auth_headers(buyer))

    assert resp.status_code == 404


def test_non_admin_can_see_published_signal_by_id(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    signal = make_signal(db_session, admin, status="published")
    buyer = make_user(db_session, "b1")

    resp = client.get(f"/liquidity-event-signals/{signal.id}", headers=auth_headers(buyer))

    assert resp.status_code == 200
    assert resp.json()["id"] == signal.id


def test_admin_can_see_draft_signal_by_id(client, db_session):
    admin = make_user(db_session, "a1", account_type="admin")
    signal = make_signal(db_session, admin, status="draft")

    resp = client.get(f"/liquidity-event-signals/{signal.id}", headers=auth_headers(admin))

    assert resp.status_code == 200


def test_get_by_id_404_when_missing(client, db_session):
    buyer = make_user(db_session, "b1")

    resp = client.get("/liquidity-event-signals/999999", headers=auth_headers(buyer))

    assert resp.status_code == 404
