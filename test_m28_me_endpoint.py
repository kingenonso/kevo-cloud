"""
Tests for M28 (2026-09-20), first slice - the GET /me endpoint added to
back the new login + dashboard shell. Returns the caller's own profile,
nothing else. Written against the REAL ~/KEVO implementation.
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

from models import Base, User as UserModel
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


def make_user(db, suffix="1", role="buyer", account_type="participant",
              kyc_status="not_started", jurisdiction=None):
    user = UserModel(
        name=f"User {suffix}",
        email=f"m28user{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        jurisdiction=jurisdiction,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_me_requires_auth(client):
    resp = client.get("/me")
    assert resp.status_code == 401


def test_me_returns_own_profile(client, db_session):
    user = make_user(db_session, "1", role="seller", account_type="participant",
                      kyc_status="verified", jurisdiction="US")
    resp = client.get("/me", headers=auth_headers(user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == user.id
    assert body["name"] == "User 1"
    assert body["role"] == "seller"
    assert body["kyc_status"] == "verified"
    assert body["jurisdiction"] == "US"
    assert body["account_type"] == "participant"


def test_me_reflects_admin_account_type(client, db_session):
    admin = make_user(db_session, "2", account_type="admin")
    resp = client.get("/me", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["account_type"] == "admin"


def test_me_never_exposes_password_hash(client, db_session):
    user = make_user(db_session, "3")
    resp = client.get("/me", headers=auth_headers(user))
    body = resp.json()
    assert "hashed_password" not in body
    assert "password" not in body


def test_me_rejects_invalid_token(client, db_session):
    resp = client.get("/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401
