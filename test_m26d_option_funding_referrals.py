"""
Tests for M26D's first slice (2026-09-19): Option Exercise Funding,
referral/tracking only.

Research found real option-exercise funders (EquityBee, Secfi, ESO Fund)
structure their product as a prepaid variable forward contract - the same
instrument class that got M25B parked over SEC swap-reclassification risk
- and comply with securities law via their own registered broker-dealer
subsidiary. KEVO builds none of that here. POST /option-funding-referrals
lets a holder request a referral; admin-only endpoints record that KEVO
pointed them at a named, real, already-licensed provider, or decline/close
the request. State machine: requested -> referred -> closed, or
requested -> withdrawn (holder) / declined (admin).
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
    Base, User as UserModel, OptionFundingReferral,
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
        email=f"m26duser{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_referral(db, holder, company="Acme Inc", status="requested"):
    referral = OptionFundingReferral(
        holder_id=holder.id, company=company, status=status,
    )
    db.add(referral)
    db.commit()
    db.refresh(referral)
    return referral


# --- POST /option-funding-referrals ---

def test_holder_can_create_referral_request(client, db_session):
    holder = make_user(db_session, "1")

    resp = client.post(
        "/option-funding-referrals", headers=auth_headers(holder),
        params={"company": "Acme Inc", "notes": "5000 vested ISOs, need ~$40k"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "requested"
    assert body["holder_id"] == holder.id
    assert body["company"] == "Acme Inc"
    assert body["notes"] == "5000 vested ISOs, need ~$40k"


def test_create_without_notes(client, db_session):
    holder = make_user(db_session, "1")
    resp = client.post(
        "/option-funding-referrals", headers=auth_headers(holder),
        params={"company": "Acme Inc"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] is None


def test_create_unauthenticated_401(client, db_session):
    resp = client.post("/option-funding-referrals", params={"company": "Acme Inc"})
    assert resp.status_code == 401


# --- PUT /option-funding-referrals/{id}/withdraw ---

def test_holder_can_withdraw_own_referral(client, db_session):
    holder = make_user(db_session, "1")
    referral = make_referral(db_session, holder)

    resp = client.put(f"/option-funding-referrals/{referral.id}/withdraw", headers=auth_headers(holder))
    assert resp.status_code == 200
    assert resp.json()["status"] == "withdrawn"


def test_non_holder_cannot_withdraw_403(client, db_session):
    holder = make_user(db_session, "1")
    stranger = make_user(db_session, "2")
    referral = make_referral(db_session, holder)

    resp = client.put(f"/option-funding-referrals/{referral.id}/withdraw", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_withdraw_wrong_status_400(client, db_session):
    holder = make_user(db_session, "1")
    referral = make_referral(db_session, holder, status="referred")

    resp = client.put(f"/option-funding-referrals/{referral.id}/withdraw", headers=auth_headers(holder))
    assert resp.status_code == 400


def test_withdraw_unknown_id_404(client, db_session):
    holder = make_user(db_session, "1")
    resp = client.put("/option-funding-referrals/999999/withdraw", headers=auth_headers(holder))
    assert resp.status_code == 404


def test_withdraw_unauthenticated_401(client, db_session):
    resp = client.put("/option-funding-referrals/1/withdraw")
    assert resp.status_code == 401


# --- PUT /option-funding-referrals/{id}/refer ---

def test_admin_can_refer(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    referral = make_referral(db_session, holder)

    resp = client.put(
        f"/option-funding-referrals/{referral.id}/refer", headers=auth_headers(admin),
        params={"referred_provider_name": "EquityBee"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "referred"
    assert body["referred_provider_name"] == "EquityBee"
    assert body["referred_at"] is not None


def test_non_admin_cannot_refer_403(client, db_session):
    holder = make_user(db_session, "1")
    referral = make_referral(db_session, holder)

    resp = client.put(
        f"/option-funding-referrals/{referral.id}/refer", headers=auth_headers(holder),
        params={"referred_provider_name": "EquityBee"},
    )
    assert resp.status_code == 403


def test_refer_wrong_status_400(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    referral = make_referral(db_session, holder, status="withdrawn")

    resp = client.put(
        f"/option-funding-referrals/{referral.id}/refer", headers=auth_headers(admin),
        params={"referred_provider_name": "EquityBee"},
    )
    assert resp.status_code == 400


def test_refer_unknown_id_404(client, db_session):
    admin = make_user(db_session, "1", account_type="admin")
    resp = client.put(
        "/option-funding-referrals/999999/refer", headers=auth_headers(admin),
        params={"referred_provider_name": "EquityBee"},
    )
    assert resp.status_code == 404


def test_refer_unauthenticated_401(client, db_session):
    resp = client.put("/option-funding-referrals/1/refer", params={"referred_provider_name": "EquityBee"})
    assert resp.status_code == 401


# --- PUT /option-funding-referrals/{id}/decline ---

def test_admin_can_decline(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    referral = make_referral(db_session, holder)

    resp = client.put(f"/option-funding-referrals/{referral.id}/decline", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["status"] == "declined"


def test_non_admin_cannot_decline_403(client, db_session):
    holder = make_user(db_session, "1")
    referral = make_referral(db_session, holder)

    resp = client.put(f"/option-funding-referrals/{referral.id}/decline", headers=auth_headers(holder))
    assert resp.status_code == 403


def test_decline_wrong_status_400(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    referral = make_referral(db_session, holder, status="referred")

    resp = client.put(f"/option-funding-referrals/{referral.id}/decline", headers=auth_headers(admin))
    assert resp.status_code == 400


def test_decline_unknown_id_404(client, db_session):
    admin = make_user(db_session, "1", account_type="admin")
    resp = client.put("/option-funding-referrals/999999/decline", headers=auth_headers(admin))
    assert resp.status_code == 404


# --- PUT /option-funding-referrals/{id}/close ---

def test_admin_can_close_referred(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    referral = make_referral(db_session, holder, status="referred")

    resp = client.put(f"/option-funding-referrals/{referral.id}/close", headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "closed"
    assert body["closed_at"] is not None


def test_non_admin_cannot_close_403(client, db_session):
    holder = make_user(db_session, "1")
    referral = make_referral(db_session, holder, status="referred")

    resp = client.put(f"/option-funding-referrals/{referral.id}/close", headers=auth_headers(holder))
    assert resp.status_code == 403


def test_close_wrong_status_400(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    referral = make_referral(db_session, holder, status="requested")

    resp = client.put(f"/option-funding-referrals/{referral.id}/close", headers=auth_headers(admin))
    assert resp.status_code == 400


def test_close_unknown_id_404(client, db_session):
    admin = make_user(db_session, "1", account_type="admin")
    resp = client.put("/option-funding-referrals/999999/close", headers=auth_headers(admin))
    assert resp.status_code == 404


# --- GET /option-funding-referrals (list) ---

def test_list_scoped_to_own_referrals(client, db_session):
    holder = make_user(db_session, "1")
    stranger = make_user(db_session, "2")
    make_referral(db_session, holder)

    resp_holder = client.get("/option-funding-referrals", headers=auth_headers(holder))
    assert resp_holder.status_code == 200
    assert len(resp_holder.json()) == 1

    resp_stranger = client.get("/option-funding-referrals", headers=auth_headers(stranger))
    assert resp_stranger.status_code == 200
    assert len(resp_stranger.json()) == 0


def test_admin_sees_all_in_list(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    make_referral(db_session, holder)

    resp = client.get("/option-funding-referrals", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_unauthenticated_401(client, db_session):
    resp = client.get("/option-funding-referrals")
    assert resp.status_code == 401


# --- GET /option-funding-referrals/{id} ---

def test_get_by_id_holder_succeeds(client, db_session):
    holder = make_user(db_session, "1")
    referral = make_referral(db_session, holder)

    resp = client.get(f"/option-funding-referrals/{referral.id}", headers=auth_headers(holder))
    assert resp.status_code == 200


def test_get_by_id_admin_succeeds(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    referral = make_referral(db_session, holder)

    resp = client.get(f"/option-funding-referrals/{referral.id}", headers=auth_headers(admin))
    assert resp.status_code == 200


def test_get_by_id_non_holder_403(client, db_session):
    holder = make_user(db_session, "1")
    stranger = make_user(db_session, "2")
    referral = make_referral(db_session, holder)

    resp = client.get(f"/option-funding-referrals/{referral.id}", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_get_by_id_unknown_404(client, db_session):
    holder = make_user(db_session, "1")
    resp = client.get("/option-funding-referrals/999999", headers=auth_headers(holder))
    assert resp.status_code == 404


def test_get_by_id_unauthenticated_401(client, db_session):
    resp = client.get("/option-funding-referrals/1")
    assert resp.status_code == 401
