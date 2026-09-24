"""
Tests for account deactivation (Batch B, item 5/13), 2026-09-24 - "make
sure the user-account-delete endpoint doesn't actually delete the
account - set it inactive with a reason instead." There was no
account-delete endpoint of any kind before this (only DELETE
/listings/{id} existed, which deletes a listing, not a user).

DELETE /users/{id} never issues a real database DELETE against the user
row - it flips is_active to False, records deactivated_at/
deactivation_reason, and revokes any session the account is currently
holding (same mechanism as /users/me/revoke-tokens). A deactivated
account can no longer log in, and any token it already holds stops
working on its very next authenticated request.

Written against the REAL ~/KEVO implementation.
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


def make_user(db, suffix="1", account_type="participant"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"deactivate{suffix}-{id(object())}@example.com",
        role="buyer",
        account_type=account_type,
        hashed_password=hash_password("originalpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_owner_can_deactivate_own_account(client, db_session):
    user = make_user(db_session, "owner1")

    resp = client.delete(f"/users/{user.id}", headers=auth_headers(user), params={"reason": "no longer need this account"})
    assert resp.status_code == 200
    body = resp.json()["user"]
    assert body["is_active"] is False
    assert body["deactivation_reason"] == "no longer need this account"
    assert body["deactivated_at"] is not None

    db_session.refresh(user)
    assert user.is_active is False
    assert user.deactivated_at is not None
    assert user.deactivation_reason == "no longer need this account"

    # never a real delete - the row is still there
    assert db_session.query(UserModel).filter(UserModel.id == user.id).count() == 1


def test_deactivate_requires_reason_400(client, db_session):
    user = make_user(db_session, "owner2")

    resp = client.delete(f"/users/{user.id}", headers=auth_headers(user), params={"reason": "   "})
    assert resp.status_code == 400

    db_session.refresh(user)
    assert user.is_active is True


def test_cannot_deactivate_already_deactivated_account_400(client, db_session):
    """
    Deactivating your OWN account also kills your own token (see
    test_deactivated_user_existing_token_stops_working), so a second
    attempt by that same user isn't even reachable with the old token -
    it 401s at the auth layer before it can hit this 400 check. An admin
    (whose own token is unaffected) is what actually exercises this path.
    """
    user = make_user(db_session, "owner3")
    admin = make_user(db_session, "admin3", account_type="admin")
    client.delete(f"/users/{user.id}", headers=auth_headers(user), params={"reason": "first time"})

    resp = client.delete(f"/users/{user.id}", headers=auth_headers(admin), params={"reason": "second time"})
    assert resp.status_code == 400


def test_admin_can_deactivate_other_user(client, db_session):
    target = make_user(db_session, "target1")
    admin = make_user(db_session, "admin1", account_type="admin")

    resp = client.delete(f"/users/{target.id}", headers=auth_headers(admin), params={"reason": "policy violation"})
    assert resp.status_code == 200

    db_session.refresh(target)
    assert target.is_active is False
    assert target.deactivation_reason == "policy violation"


def test_non_admin_non_owner_cannot_deactivate_403(client, db_session):
    target = make_user(db_session, "target2")
    stranger = make_user(db_session, "stranger1")

    resp = client.delete(f"/users/{target.id}", headers=auth_headers(stranger), params={"reason": "trying to mess with someone else"})
    assert resp.status_code == 403

    db_session.refresh(target)
    assert target.is_active is True


def test_deactivate_unknown_user_404(client, db_session):
    user = make_user(db_session, "owner4")
    resp = client.delete("/users/999999", headers=auth_headers(user), params={"reason": "doesn't matter"})
    assert resp.status_code == 404


def test_deactivate_unauthenticated_401(client, db_session):
    user = make_user(db_session, "owner5")
    resp = client.delete(f"/users/{user.id}", params={"reason": "no auth header"})
    assert resp.status_code == 401


def test_deactivated_user_cannot_login_403(client, db_session):
    user = make_user(db_session, "owner6")
    client.delete(f"/users/{user.id}", headers=auth_headers(user), params={"reason": "leaving"})

    resp = client.post("/login", json={"email": user.email, "password": "originalpass123"})
    assert resp.status_code == 403
    assert "deactivated" in resp.json()["detail"].lower()


def test_deactivated_user_existing_token_stops_working(client, db_session):
    user = make_user(db_session, "owner7")
    token_headers = auth_headers(user)

    # token works before deactivation
    pre_resp = client.get("/users", headers=token_headers)
    assert pre_resp.status_code == 200

    client.delete(f"/users/{user.id}", headers=token_headers, params={"reason": "leaving"})

    # the exact same token no longer works, on the very next request
    post_resp = client.get("/users", headers=token_headers)
    assert post_resp.status_code == 401
