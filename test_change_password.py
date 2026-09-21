"""
Tests for the new PUT /change-password endpoint, 2026-09-21 - closes part
of the M28 "password-reset UI" gap. This is NOT a forgot-password flow
(that needs real email infrastructure, flagged as a separate future item
under M18) - it's a change-password action for an already-logged-in user,
requiring their current password. Written against the REAL ~/KEVO
implementation.
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


def make_user(db, suffix="1", password="originalpass123"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"changepw{suffix}-{id(object())}@example.com",
        role="buyer",
        account_type="participant",
        hashed_password=hash_password(password) if password else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_change_password_succeeds_with_correct_current_password(client, db_session):
    user = make_user(db_session, "1", password="originalpass123")

    resp = client.put(
        "/change-password",
        json={"current_password": "originalpass123", "new_password": "newpass456"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200

    login_resp = client.post("/login", json={"email": user.email, "password": "newpass456"})
    assert login_resp.status_code == 200


def test_change_password_rejects_wrong_current_password(client, db_session):
    user = make_user(db_session, "1", password="originalpass123")

    resp = client.put(
        "/change-password",
        json={"current_password": "wrongpass", "new_password": "newpass456"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 401


def test_change_password_old_password_no_longer_works(client, db_session):
    user = make_user(db_session, "1", password="originalpass123")

    client.put(
        "/change-password",
        json={"current_password": "originalpass123", "new_password": "newpass456"},
        headers=auth_headers(user),
    )

    login_resp = client.post("/login", json={"email": user.email, "password": "originalpass123"})
    assert login_resp.status_code == 401


def test_change_password_unauthenticated_401(client, db_session):
    resp = client.put(
        "/change-password",
        json={"current_password": "originalpass123", "new_password": "newpass456"},
    )
    assert resp.status_code == 401


def test_change_password_legacy_user_with_no_password_400(client, db_session):
    user = make_user(db_session, "1", password=None)

    resp = client.put(
        "/change-password",
        json={"current_password": "anything", "new_password": "newpass456"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 400
