"""
Tests for M22 (2026-09-18), "quick wins" security-hardening slice: account
lockout after repeated failed logins, rate limiting on the login endpoint,
and standard security-response headers applied globally. Written against
the REAL ~/KEVO implementation.
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
    limiter,
    MAX_FAILED_LOGIN_ATTEMPTS,
    LOCKOUT_DURATION_MINUTES,
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


@pytest.fixture()
def enable_rate_limiting():
    limiter.enabled = True
    yield
    limiter.enabled = False


def auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def make_user(db, suffix="1", role="buyer", account_type="participant", password="testpass123"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"m22user{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        hashed_password=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Account lockout
# ---------------------------------------------------------------------------

def test_wrong_password_increments_failed_attempts(client, db_session):
    user = make_user(db_session, "lockout1")
    client.post("/login", json={"email": user.email, "password": "wrongpass"})
    db_session.refresh(user)
    assert user.failed_login_attempts == 1
    assert user.locked_until is None


def test_account_locks_after_max_failed_attempts(client, db_session):
    user = make_user(db_session, "lockout2")
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        resp = client.post("/login", json={"email": user.email, "password": "wrongpass"})
        assert resp.status_code == 401
    db_session.refresh(user)
    assert user.locked_until is not None
    assert user.locked_until > datetime.utcnow()
    assert user.failed_login_attempts == 0


def test_locked_account_rejects_even_correct_password(client, db_session):
    user = make_user(db_session, "lockout3", password="correctpass")
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        client.post("/login", json={"email": user.email, "password": "wrongpass"})
    resp = client.post("/login", json={"email": user.email, "password": "correctpass"})
    assert resp.status_code == 423


def test_lockout_expires_and_allows_login_again(client, db_session):
    user = make_user(db_session, "lockout4", password="correctpass")
    user.locked_until = datetime.utcnow() - timedelta(minutes=1)
    user.failed_login_attempts = MAX_FAILED_LOGIN_ATTEMPTS
    db_session.commit()

    resp = client.post("/login", json={"email": user.email, "password": "correctpass"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_successful_login_clears_lockout_state(client, db_session):
    user = make_user(db_session, "lockout5", password="correctpass")
    client.post("/login", json={"email": user.email, "password": "wrongpass"})
    db_session.refresh(user)
    assert user.failed_login_attempts == 1

    resp = client.post("/login", json={"email": user.email, "password": "correctpass"})
    assert resp.status_code == 200
    db_session.refresh(user)
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


def test_nonexistent_user_login_does_not_error(client, db_session):
    resp = client.post("/login", json={"email": "nobody@example.com", "password": "whatever"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

def test_security_headers_present_on_response(client, db_session):
    resp = client.post("/login", json={"email": "nobody@example.com", "password": "whatever"})
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert "max-age" in resp.headers.get("strict-transport-security", "")
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def test_login_endpoint_enforces_rate_limit(client, db_session, enable_rate_limiting):
    for _ in range(5):
        resp = client.post("/login", json={"email": "ratelimit-test@example.com", "password": "x"})
        assert resp.status_code == 401
    resp = client.post("/login", json={"email": "ratelimit-test@example.com", "password": "x"})
    assert resp.status_code == 429
