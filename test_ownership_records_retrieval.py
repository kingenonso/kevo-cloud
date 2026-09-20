"""
Tests for the ownership-records retrieval endpoint (2026-09-20): GET
/ownership-records. Added while building the M26B (share-backed lending)
frontend - a holder needs to pick a real, verified OwnershipRecord id for
the loan request form, but there was previously no GET endpoint anywhere
for OwnershipRecord. Written against the REAL ~/KEVO implementation.
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

from models import Base, User as UserModel, OwnershipRecord
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
        email=f"own{suffix}-{id(object())}@example.com",
        role="seller",
        hashed_password=hash_password("testpass123"),
        account_type=account_type,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_ownership_record(db, seller, company="KEVO Test Co", quantity=100, verification_status="pending"):
    record = OwnershipRecord(
        seller_id=seller.id,
        company=company,
        asset_type="common_stock",
        quantity=quantity,
        verification_status=verification_status,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def test_get_ownership_records_requires_auth(client, db_session):
    resp = client.get("/ownership-records")
    assert resp.status_code == 401


def test_owner_sees_own_records(client, db_session):
    user = make_user(db_session, "1")
    make_ownership_record(db_session, user, "Company A")
    make_ownership_record(db_session, user, "Company B")

    resp = client.get("/ownership-records", headers=auth_headers(user))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert {r["company"] for r in body} == {"Company A", "Company B"}


def test_records_scoped_away_from_other_users(client, db_session):
    owner = make_user(db_session, "2")
    other = make_user(db_session, "3")
    make_ownership_record(db_session, owner, "Owner's Company")

    resp = client.get("/ownership-records", headers=auth_headers(other))
    assert resp.status_code == 200
    assert resp.json() == []


def test_admin_sees_all(client, db_session):
    owner = make_user(db_session, "4")
    admin = make_user(db_session, "5", account_type="admin")
    make_ownership_record(db_session, owner, "Owner's Company")

    resp = client.get("/ownership-records", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_empty_list_when_no_records(client, db_session):
    user = make_user(db_session, "6")

    resp = client.get("/ownership-records", headers=auth_headers(user))
    assert resp.status_code == 200
    assert resp.json() == []
