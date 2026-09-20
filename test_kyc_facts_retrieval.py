"""
Tests for the KYC-facts retrieval endpoint (2026-09-20): GET
/kyc-facts/user/{user_id}. Added while starting the "surface the hidden
backend" frontend push - KYC facts could be created (POST /kyc-facts) and
verified (PUT /kyc-facts/{fact_id}/verify) but there was previously no way
to read them back. Written against the REAL ~/KEVO implementation.
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

from models import Base, User as UserModel, KYCFact
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
        email=f"kyc{suffix}-{id(object())}@example.com",
        role="buyer",
        hashed_password=hash_password("testpass123"),
        account_type=account_type,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_kyc_fact(db, user, fact_type="full_legal_name", fact_value="Jane Doe"):
    fact = KYCFact(
        user_id=user.id,
        jurisdiction="US",
        fact_type=fact_type,
        fact_value=fact_value,
    )
    db.add(fact)
    db.commit()
    db.refresh(fact)
    return fact


def test_get_kyc_facts_requires_auth(client, db_session):
    user = make_user(db_session, "1")

    resp = client.get(f"/kyc-facts/user/{user.id}")
    assert resp.status_code == 401


def test_owner_can_view_own_facts(client, db_session):
    user = make_user(db_session, "2")
    make_kyc_fact(db_session, user, "full_legal_name", "Jane Doe")
    make_kyc_fact(db_session, user, "date_of_birth", "1990-01-01")

    resp = client.get(f"/kyc-facts/user/{user.id}", headers=auth_headers(user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == user.id
    assert body["kyc_status"] == user.kyc_status
    assert len(body["kyc_facts"]) == 2


def test_non_owner_non_admin_forbidden(client, db_session):
    owner = make_user(db_session, "3")
    other = make_user(db_session, "4")
    make_kyc_fact(db_session, owner)

    resp = client.get(f"/kyc-facts/user/{owner.id}", headers=auth_headers(other))
    assert resp.status_code == 403


def test_admin_can_view_any_user_facts(client, db_session):
    owner = make_user(db_session, "5")
    admin = make_user(db_session, "6", account_type="admin")
    make_kyc_fact(db_session, owner)

    resp = client.get(f"/kyc-facts/user/{owner.id}", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()["kyc_facts"]) == 1


def test_404_for_missing_user(client, db_session):
    admin = make_user(db_session, "7", account_type="admin")

    resp = client.get("/kyc-facts/user/999999", headers=auth_headers(admin))
    assert resp.status_code == 404
