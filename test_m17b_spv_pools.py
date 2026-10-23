"""
Tests for M17B's SPV Fractional Ownership Pools, back-office-
administrator-only scope (POST/GET/close/cancel /spv-pools,
POST/GET /spv-pools/{id}/commitments, PUT /spv-pool-commitments/{id}/
withdraw), 2026-10-22.

M17B was formally deferred on 2026-09-12 (claude/kevo-m17b-spv-critical-
assessment.md) because the originally-scoped "KEVO itself sponsors/
pools user capital" shape needs broker-dealer or investment-adviser
registration KEVO doesn't have. That research also found a third real
model - a pure back-office administrator with no sponsor role at all
(Sydecar/Carta/Allocations) - which doesn't need that registration.
Confirmed with Eze via AskUserQuestion, 2026-10-22: build that model.
KEVO is never the pool's sponsor; sponsor_name names whoever actually
is, and legal_disclaimer_acknowledged must be explicitly true.

Written against the real ~/KEVO implementation, same fixture pattern as
test_m31_liquidity_event_radar.py.
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

from models import Base, User as UserModel, Listing as ListingModel, SpvPool, SpvPoolCommitment
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
        email=f"spv{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller):
    listing = ListingModel(
        seller_id=seller.id,
        company="Acme Inc",
        asset_type="Private Shares",
        quantity=1000,
        asking_price=50000.0,
        is_transferable=True,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


VALID_PAYLOAD = {
    "company": "Acme Inc",
    "asset_type": "Private Shares",
    "sponsor_name": "Acme Pooling SPV LLC",
    "minimum_check_size": 5000.0,
    "legal_disclaimer_acknowledged": True,
}


# --- POST /spv-pools ---

def test_create_pool_succeeds_with_disclaimer_acknowledged(client, db_session):
    organizer = make_user(db_session, "o1")

    resp = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer))

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "forming"
    assert data["sponsor_name"] == "Acme Pooling SPV LLC"
    assert data["organizer_id"] == organizer.id
    assert "not the sponsor" in data["disclaimer"]


def test_create_pool_requires_disclaimer_acknowledgement(client, db_session):
    organizer = make_user(db_session, "o1")
    payload = {**VALID_PAYLOAD, "legal_disclaimer_acknowledged": False}

    resp = client.post("/spv-pools", params=payload, headers=auth_headers(organizer))

    assert resp.status_code == 400
    assert "legal_disclaimer_acknowledged" in resp.json()["detail"]


def test_create_pool_requires_sponsor_name(client, db_session):
    organizer = make_user(db_session, "o1")
    payload = {**VALID_PAYLOAD, "sponsor_name": "   "}

    resp = client.post("/spv-pools", params=payload, headers=auth_headers(organizer))

    assert resp.status_code == 400
    assert "sponsor_name" in resp.json()["detail"]


def test_create_pool_rejects_non_positive_minimum_check_size(client, db_session):
    organizer = make_user(db_session, "o1")
    payload = {**VALID_PAYLOAD, "minimum_check_size": 0}

    resp = client.post("/spv-pools", params=payload, headers=auth_headers(organizer))

    assert resp.status_code == 400
    assert "minimum_check_size" in resp.json()["detail"]


def test_create_pool_rejects_target_below_minimum(client, db_session):
    organizer = make_user(db_session, "o1")
    payload = {**VALID_PAYLOAD, "target_total_amount": 1000}

    resp = client.post("/spv-pools", params=payload, headers=auth_headers(organizer))

    assert resp.status_code == 400
    assert "target_total_amount" in resp.json()["detail"]


def test_create_pool_requires_auth(client, db_session):
    resp = client.post("/spv-pools", params=VALID_PAYLOAD)

    assert resp.status_code == 401


def test_create_pool_validates_target_listing_exists(client, db_session):
    organizer = make_user(db_session, "o1")
    payload = {**VALID_PAYLOAD, "target_listing_id": 999999}

    resp = client.post("/spv-pools", params=payload, headers=auth_headers(organizer))

    assert resp.status_code == 404


def test_create_pool_accepts_real_target_listing(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    organizer = make_user(db_session, "o1")
    payload = {**VALID_PAYLOAD, "target_listing_id": listing.id}

    resp = client.post("/spv-pools", params=payload, headers=auth_headers(organizer))

    assert resp.status_code == 200
    assert resp.json()["target_listing_id"] == listing.id


def test_create_pool_no_fee_field_exists_anywhere_in_response(client, db_session):
    """
    Direct proof of the design invariant: nothing in the response shape
    names a KEVO fee of any kind - staying outside the AngelList no-
    action letter's no-transaction-fee condition by never charging one,
    rather than attempting to satisfy it.
    """
    organizer = make_user(db_session, "o1")

    resp = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer))

    data = resp.json()
    assert not any("fee" in key.lower() for key in data.keys())


# --- GET /spv-pools ---

def test_any_authenticated_user_can_browse_pools(client, db_session):
    organizer = make_user(db_session, "o1")
    client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer))
    viewer = make_user(db_session, "v1")

    resp = client.get("/spv-pools", headers=auth_headers(viewer))

    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_pools_filters_by_company_asset_type_status(client, db_session):
    organizer = make_user(db_session, "o1")
    client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer))
    other_payload = {**VALID_PAYLOAD, "company": "Other Co"}
    client.post("/spv-pools", params=other_payload, headers=auth_headers(organizer))

    resp = client.get("/spv-pools", params={"company": "Acme Inc"}, headers=auth_headers(organizer))

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["company"] == "Acme Inc"


def test_get_pools_requires_auth(client, db_session):
    resp = client.get("/spv-pools")

    assert resp.status_code == 401


# --- GET /spv-pools/{id} ---

def test_get_pool_by_id(client, db_session):
    organizer = make_user(db_session, "o1")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()
    viewer = make_user(db_session, "v1")

    resp = client.get(f"/spv-pools/{created['id']}", headers=auth_headers(viewer))

    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_pool_404_when_missing(client, db_session):
    organizer = make_user(db_session, "o1")

    resp = client.get("/spv-pools/999999", headers=auth_headers(organizer))

    assert resp.status_code == 404


# --- PUT /spv-pools/{id}/close and /cancel ---

def test_organizer_can_close_forming_pool(client, db_session):
    organizer = make_user(db_session, "o1")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()

    resp = client.put(f"/spv-pools/{created['id']}/close", headers=auth_headers(organizer))

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "closed"
    assert data["closed_at"] is not None


def test_non_organizer_non_admin_cannot_close_pool(client, db_session):
    organizer = make_user(db_session, "o1")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()
    stranger = make_user(db_session, "s1")

    resp = client.put(f"/spv-pools/{created['id']}/close", headers=auth_headers(stranger))

    assert resp.status_code == 403


def test_admin_can_close_any_pool(client, db_session):
    organizer = make_user(db_session, "o1")
    admin = make_user(db_session, "a1", account_type="admin")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()

    resp = client.put(f"/spv-pools/{created['id']}/close", headers=auth_headers(admin))

    assert resp.status_code == 200


def test_cannot_close_already_closed_pool(client, db_session):
    organizer = make_user(db_session, "o1")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()
    client.put(f"/spv-pools/{created['id']}/close", headers=auth_headers(organizer))

    resp = client.put(f"/spv-pools/{created['id']}/close", headers=auth_headers(organizer))

    assert resp.status_code == 400


def test_organizer_can_cancel_forming_pool(client, db_session):
    organizer = make_user(db_session, "o1")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()

    resp = client.put(f"/spv-pools/{created['id']}/cancel", headers=auth_headers(organizer))

    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_non_organizer_cannot_cancel_pool(client, db_session):
    organizer = make_user(db_session, "o1")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()
    stranger = make_user(db_session, "s1")

    resp = client.put(f"/spv-pools/{created['id']}/cancel", headers=auth_headers(stranger))

    assert resp.status_code == 403


# --- POST /spv-pools/{id}/commitments ---

def test_participant_can_commit_at_or_above_minimum(client, db_session):
    organizer = make_user(db_session, "o1")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()
    participant = make_user(db_session, "p1")

    resp = client.post(
        f"/spv-pools/{created['id']}/commitments",
        params={"committed_amount": 5000.0},
        headers=auth_headers(participant),
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["participant_id"] == participant.id
    assert "non-binding" in data["disclaimer"]


def test_commitment_rejected_below_minimum_check_size(client, db_session):
    organizer = make_user(db_session, "o1")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()
    participant = make_user(db_session, "p1")

    resp = client.post(
        f"/spv-pools/{created['id']}/commitments",
        params={"committed_amount": 1000.0},
        headers=auth_headers(participant),
    )

    assert resp.status_code == 400
    assert "minimum check size" in resp.json()["detail"]


def test_commitment_rejected_on_closed_pool(client, db_session):
    organizer = make_user(db_session, "o1")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()
    client.put(f"/spv-pools/{created['id']}/close", headers=auth_headers(organizer))
    participant = make_user(db_session, "p1")

    resp = client.post(
        f"/spv-pools/{created['id']}/commitments",
        params={"committed_amount": 5000.0},
        headers=auth_headers(participant),
    )

    assert resp.status_code == 400


def test_commitment_404_on_missing_pool(client, db_session):
    participant = make_user(db_session, "p1")

    resp = client.post(
        "/spv-pools/999999/commitments",
        params={"committed_amount": 5000.0},
        headers=auth_headers(participant),
    )

    assert resp.status_code == 404


# --- GET /spv-pools/{id}/commitments ---

def test_organizer_sees_all_commitments(client, db_session):
    organizer = make_user(db_session, "o1")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()
    p1 = make_user(db_session, "p1")
    p2 = make_user(db_session, "p2")
    client.post(f"/spv-pools/{created['id']}/commitments", params={"committed_amount": 5000.0}, headers=auth_headers(p1))
    client.post(f"/spv-pools/{created['id']}/commitments", params={"committed_amount": 6000.0}, headers=auth_headers(p2))

    resp = client.get(f"/spv-pools/{created['id']}/commitments", headers=auth_headers(organizer))

    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_participant_sees_only_their_own_commitment(client, db_session):
    organizer = make_user(db_session, "o1")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()
    p1 = make_user(db_session, "p1")
    p2 = make_user(db_session, "p2")
    client.post(f"/spv-pools/{created['id']}/commitments", params={"committed_amount": 5000.0}, headers=auth_headers(p1))
    client.post(f"/spv-pools/{created['id']}/commitments", params={"committed_amount": 6000.0}, headers=auth_headers(p2))

    resp = client.get(f"/spv-pools/{created['id']}/commitments", headers=auth_headers(p1))

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["participant_id"] == p1.id


def test_admin_sees_all_commitments_on_any_pool(client, db_session):
    organizer = make_user(db_session, "o1")
    admin = make_user(db_session, "a1", account_type="admin")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()
    p1 = make_user(db_session, "p1")
    client.post(f"/spv-pools/{created['id']}/commitments", params={"committed_amount": 5000.0}, headers=auth_headers(p1))

    resp = client.get(f"/spv-pools/{created['id']}/commitments", headers=auth_headers(admin))

    assert resp.status_code == 200
    assert len(resp.json()) == 1


# --- PUT /spv-pool-commitments/{id}/withdraw ---

def test_participant_can_withdraw_own_commitment(client, db_session):
    organizer = make_user(db_session, "o1")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()
    participant = make_user(db_session, "p1")
    commitment = client.post(
        f"/spv-pools/{created['id']}/commitments",
        params={"committed_amount": 5000.0},
        headers=auth_headers(participant),
    ).json()

    resp = client.put(f"/spv-pool-commitments/{commitment['id']}/withdraw", headers=auth_headers(participant))

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "withdrawn"
    assert data["withdrawn_at"] is not None


def test_non_owner_cannot_withdraw_commitment(client, db_session):
    organizer = make_user(db_session, "o1")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()
    participant = make_user(db_session, "p1")
    stranger = make_user(db_session, "s1")
    commitment = client.post(
        f"/spv-pools/{created['id']}/commitments",
        params={"committed_amount": 5000.0},
        headers=auth_headers(participant),
    ).json()

    resp = client.put(f"/spv-pool-commitments/{commitment['id']}/withdraw", headers=auth_headers(stranger))

    assert resp.status_code == 403


def test_cannot_withdraw_already_withdrawn_commitment(client, db_session):
    organizer = make_user(db_session, "o1")
    created = client.post("/spv-pools", params=VALID_PAYLOAD, headers=auth_headers(organizer)).json()
    participant = make_user(db_session, "p1")
    commitment = client.post(
        f"/spv-pools/{created['id']}/commitments",
        params={"committed_amount": 5000.0},
        headers=auth_headers(participant),
    ).json()
    client.put(f"/spv-pool-commitments/{commitment['id']}/withdraw", headers=auth_headers(participant))

    resp = client.put(f"/spv-pool-commitments/{commitment['id']}/withdraw", headers=auth_headers(participant))

    assert resp.status_code == 400


def test_withdraw_404_on_missing_commitment(client, db_session):
    participant = make_user(db_session, "p1")

    resp = client.put("/spv-pool-commitments/999999/withdraw", headers=auth_headers(participant))

    assert resp.status_code == 404
