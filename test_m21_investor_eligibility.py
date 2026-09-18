"""
Tests for M21 (2026-09-18), first slice - the real gap found during the
audit: InvestorEligibility (built under M13, self-submit/admin-verify per
M19) had no GET retrieval endpoint at all. Mirrors the exact
buyer-scoped/admin-sees-all pattern already used for
GET /transactions and GET /buyer-interests. Written against the REAL
~/KEVO implementation.
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

from models import Base, User as UserModel, InvestorEligibility
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


def make_user(db, suffix="1", role="buyer", account_type="participant"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"m21user{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_eligibility(db, buyer, classification="accredited", status="pending"):
    record = InvestorEligibility(
        buyer_id=buyer.id,
        investor_type="individual",
        classification=classification,
        status=status,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


# --- GET /investor-eligibility ---

def test_list_returns_empty_when_none_exist(client, db_session):
    buyer = make_user(db_session, "1")
    resp = client.get("/investor-eligibility", headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_returns_own_records_only(client, db_session):
    buyer1 = make_user(db_session, "1")
    buyer2 = make_user(db_session, "2")
    make_eligibility(db_session, buyer1)
    make_eligibility(db_session, buyer2)

    resp = client.get("/investor-eligibility", headers=auth_headers(buyer1))
    assert resp.status_code == 200
    records = resp.json()
    assert len(records) == 1
    assert records[0]["buyer_id"] == buyer1.id


def test_list_admin_sees_all(client, db_session):
    buyer1 = make_user(db_session, "1")
    buyer2 = make_user(db_session, "2")
    admin = make_user(db_session, "3", account_type="admin")
    make_eligibility(db_session, buyer1)
    make_eligibility(db_session, buyer2)

    resp = client.get("/investor-eligibility", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_returns_correct_fields(client, db_session):
    buyer = make_user(db_session, "1")
    make_eligibility(db_session, buyer, classification="sophisticated", status="verified")

    resp = client.get("/investor-eligibility", headers=auth_headers(buyer))
    record = resp.json()[0]
    assert record["classification"] == "sophisticated"
    assert record["status"] == "verified"
    assert record["investor_type"] == "individual"


def test_list_unauthenticated_401(client, db_session):
    resp = client.get("/investor-eligibility")
    assert resp.status_code == 401


# --- GET /investor-eligibility/{id} ---

def test_get_by_id_returns_correct_record(client, db_session):
    buyer = make_user(db_session, "1")
    record = make_eligibility(db_session, buyer)

    resp = client.get(f"/investor-eligibility/{record.id}", headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert resp.json()["investor_eligibility"]["id"] == record.id


def test_get_by_id_404_for_unknown_id(client, db_session):
    buyer = make_user(db_session, "1")
    resp = client.get("/investor-eligibility/999999", headers=auth_headers(buyer))
    assert resp.status_code == 404


def test_get_by_id_403_for_other_users_record(client, db_session):
    buyer1 = make_user(db_session, "1")
    buyer2 = make_user(db_session, "2")
    record = make_eligibility(db_session, buyer1)

    resp = client.get(f"/investor-eligibility/{record.id}", headers=auth_headers(buyer2))
    assert resp.status_code == 403


def test_get_by_id_admin_can_view_any_record(client, db_session):
    buyer = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    record = make_eligibility(db_session, buyer)

    resp = client.get(f"/investor-eligibility/{record.id}", headers=auth_headers(admin))
    assert resp.status_code == 200


def test_get_by_id_unauthenticated_401(client, db_session):
    buyer = make_user(db_session, "1")
    record = make_eligibility(db_session, buyer)
    resp = client.get(f"/investor-eligibility/{record.id}")
    assert resp.status_code == 401
