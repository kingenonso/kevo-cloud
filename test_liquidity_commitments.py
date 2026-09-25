"""
Tests for M31's Liquidity Commitment (POST/GET/withdraw
/liquidity-commitments), 2026-09-25 - a richer, parameterized standing
interest, deliberately pure data capture: nothing matches or acts on it
automatically. Written against the real ~/KEVO implementation.
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

from models import Base, User as UserModel, LiquidityCommitment
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
        email=f"liqcommit{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_commitment(db, buyer, status="active"):
    c = LiquidityCommitment(
        buyer_id=buyer.id, company="Acme Inc", asset_type="Private Shares",
        min_quantity=10, max_quantity=100, min_price=5, max_price=15,
        status=status, created_at=__import__("datetime").datetime.utcnow(),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


BASE_PAYLOAD = {
    "company": "Acme Inc",
    "asset_type": "Private Shares",
    "min_quantity": 10,
    "max_quantity": 100,
    "min_price": 5,
    "max_price": 15,
}


# --- POST /liquidity-commitments ---

def test_buyer_can_create_own_commitment(client, db_session):
    buyer = make_user(db_session, "1")
    resp = client.post(
        "/liquidity-commitments",
        json={**BASE_PAYLOAD, "buyer_id": buyer.id},
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["buyer_id"] == buyer.id
    assert body["status"] == "active"
    assert "not a binding commitment" in body["disclaimer"]


def test_cannot_create_for_another_buyer_403(client, db_session):
    buyer = make_user(db_session, "1")
    other = make_user(db_session, "2")
    resp = client.post(
        "/liquidity-commitments",
        json={**BASE_PAYLOAD, "buyer_id": other.id},
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 403


def test_admin_can_create_for_any_buyer(client, db_session):
    buyer = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    resp = client.post(
        "/liquidity-commitments",
        json={**BASE_PAYLOAD, "buyer_id": buyer.id},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200


def test_min_greater_than_max_quantity_400(client, db_session):
    buyer = make_user(db_session, "1")
    payload = {**BASE_PAYLOAD, "buyer_id": buyer.id, "min_quantity": 200, "max_quantity": 100}
    resp = client.post("/liquidity-commitments", json=payload, headers=auth_headers(buyer))
    assert resp.status_code == 400


def test_min_greater_than_max_price_400(client, db_session):
    buyer = make_user(db_session, "1")
    payload = {**BASE_PAYLOAD, "buyer_id": buyer.id, "min_price": 50, "max_price": 15}
    resp = client.post("/liquidity-commitments", json=payload, headers=auth_headers(buyer))
    assert resp.status_code == 400


def test_create_unauthenticated_401(client, db_session):
    buyer = make_user(db_session, "1")
    resp = client.post("/liquidity-commitments", json={**BASE_PAYLOAD, "buyer_id": buyer.id})
    assert resp.status_code == 401


# --- GET /liquidity-commitments ---

def test_list_scoped_to_own_admin_sees_all(client, db_session):
    buyer_a = make_user(db_session, "1")
    buyer_b = make_user(db_session, "2")
    admin = make_user(db_session, "3", account_type="admin")
    make_commitment(db_session, buyer_a)
    make_commitment(db_session, buyer_b)

    resp_a = client.get("/liquidity-commitments", headers=auth_headers(buyer_a))
    assert resp_a.status_code == 200
    assert len(resp_a.json()) == 1
    assert resp_a.json()[0]["buyer_id"] == buyer_a.id

    resp_admin = client.get("/liquidity-commitments", headers=auth_headers(admin))
    assert resp_admin.status_code == 200
    assert len(resp_admin.json()) == 2


# --- GET /liquidity-commitments/{id} ---

def test_get_owner_200_stranger_403(client, db_session):
    buyer = make_user(db_session, "1")
    stranger = make_user(db_session, "2")
    c = make_commitment(db_session, buyer)

    resp_owner = client.get(f"/liquidity-commitments/{c.id}", headers=auth_headers(buyer))
    assert resp_owner.status_code == 200

    resp_stranger = client.get(f"/liquidity-commitments/{c.id}", headers=auth_headers(stranger))
    assert resp_stranger.status_code == 403


def test_get_not_found_404(client, db_session):
    buyer = make_user(db_session, "1")
    resp = client.get("/liquidity-commitments/999999", headers=auth_headers(buyer))
    assert resp.status_code == 404


# --- PUT /liquidity-commitments/{id}/withdraw ---

def test_owner_can_withdraw(client, db_session):
    buyer = make_user(db_session, "1")
    c = make_commitment(db_session, buyer)

    resp = client.put(f"/liquidity-commitments/{c.id}/withdraw", headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert resp.json()["status"] == "withdrawn"


def test_stranger_cannot_withdraw_403(client, db_session):
    buyer = make_user(db_session, "1")
    stranger = make_user(db_session, "2")
    c = make_commitment(db_session, buyer)

    resp = client.put(f"/liquidity-commitments/{c.id}/withdraw", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_admin_cannot_withdraw_someone_elses(client, db_session):
    buyer = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    c = make_commitment(db_session, buyer)

    resp = client.put(f"/liquidity-commitments/{c.id}/withdraw", headers=auth_headers(admin))
    assert resp.status_code == 403
