"""
Tests for M22's audit trail and token revocation mechanism (Batch B, group 3
item 8), 2026-09-24 - covers:
  - get_current_user rejecting a token issued before tokens_valid_since
  - get_current_user accepting a token issued after tokens_valid_since
  - POST /users/me/revoke-tokens
  - GET /audit-log admin-only gate
  - that login/password/KYC/evidence/compliance-rule actions each log the
    right audit row (actor_user_id, action, target_type, target_id)

Written against the REAL ~/KEVO implementation.
"""
import os
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

import jwt
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, User as UserModel, AuditLogEntry, ComplianceRule, Evidence
from app import app, get_db, hash_password, create_access_token, SECRET_KEY, JWT_ALGORITHM


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
        email=f"audittest{suffix}-{id(object())}@example.com",
        role="buyer",
        account_type=account_type,
        hashed_password=hash_password("originalpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_token_with_iat(user_id, iat_dt):
    payload = {"sub": str(user_id), "iat": iat_dt, "exp": iat_dt + timedelta(minutes=30)}
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


# ---------- token revocation ----------

def test_token_issued_before_revocation_is_rejected(client, db_session):
    user = make_user(db_session, "revoke1")
    old_token = make_token_with_iat(user.id, datetime.utcnow() - timedelta(minutes=5))

    user.tokens_valid_since = datetime.utcnow()
    db_session.commit()

    resp = client.get("/audit-log", headers={"Authorization": f"Bearer {old_token}"})
    assert resp.status_code == 401
    assert "revoked" in resp.json()["detail"].lower()


def test_token_issued_after_revocation_is_accepted(client, db_session):
    user = make_user(db_session, "revoke2", account_type="admin")
    user.tokens_valid_since = datetime.utcnow() - timedelta(minutes=5)
    db_session.commit()

    fresh_token = make_token_with_iat(user.id, datetime.utcnow())

    resp = client.get("/audit-log", headers={"Authorization": f"Bearer {fresh_token}"})
    assert resp.status_code == 200


def test_user_with_no_tokens_valid_since_is_unaffected(client, db_session):
    user = make_user(db_session, "revoke3")
    assert user.tokens_valid_since is None

    resp = client.get("/audit-log", headers=auth_headers(user))
    # not revoked, but not admin either - should be 403, not 401
    assert resp.status_code == 403


def test_revoke_my_tokens_endpoint_sets_tokens_valid_since_and_logs(client, db_session):
    user = make_user(db_session, "revoke4")
    old_token = make_token_with_iat(user.id, datetime.utcnow() - timedelta(minutes=5))

    resp = client.post("/users/me/revoke-tokens", headers={"Authorization": f"Bearer {old_token}"})
    assert resp.status_code == 200

    db_session.refresh(user)
    assert user.tokens_valid_since is not None

    entry = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.action == "tokens_revoked",
        AuditLogEntry.actor_user_id == user.id,
    ).first()
    assert entry is not None
    assert entry.target_type == "user"
    assert entry.target_id == user.id


def test_revoke_my_tokens_actually_invalidates_the_calling_token(client, db_session):
    user = make_user(db_session, "revoke5")
    token = make_token_with_iat(user.id, datetime.utcnow() - timedelta(minutes=5))
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/users/me/revoke-tokens", headers=headers)
    assert resp.status_code == 200

    resp2 = client.post("/users/me/revoke-tokens", headers=headers)
    assert resp2.status_code == 401


# ---------- audit log admin gate ----------

def test_audit_log_requires_admin(client, db_session):
    user = make_user(db_session, "nonadmin1", account_type="participant")
    resp = client.get("/audit-log", headers=auth_headers(user))
    assert resp.status_code == 403


def test_audit_log_accessible_to_admin(client, db_session):
    admin = make_user(db_session, "admin1", account_type="admin")
    resp = client.get("/audit-log", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------- individual audit events ----------

def test_login_success_is_logged(client, db_session):
    user = make_user(db_session, "loginok1")
    resp = client.post("/login", json={"email": user.email, "password": "originalpass123"})
    assert resp.status_code == 200

    entry = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.action == "login_success",
        AuditLogEntry.actor_user_id == user.id,
    ).first()
    assert entry is not None


def test_login_wrong_password_is_logged(client, db_session):
    user = make_user(db_session, "loginbad1")
    resp = client.post("/login", json={"email": user.email, "password": "wrongpassword"})
    assert resp.status_code == 401

    entry = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.action == "login_failed_wrong_password",
        AuditLogEntry.actor_user_id == user.id,
    ).first()
    assert entry is not None


def test_login_unknown_email_is_logged_with_null_actor(client, db_session):
    resp = client.post("/login", json={"email": "nobody-at-all@example.com", "password": "whatever123"})
    assert resp.status_code == 401

    entry = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.action == "login_failed_unknown_email",
    ).first()
    assert entry is not None
    assert entry.actor_user_id is None
    assert entry.detail == "nobody-at-all@example.com"


def test_password_changed_is_logged_and_revokes_tokens(client, db_session):
    user = make_user(db_session, "pwchange1")
    old_token = make_token_with_iat(user.id, datetime.utcnow() - timedelta(minutes=5))

    resp = client.put(
        "/change-password",
        json={"current_password": "originalpass123", "new_password": "newpass456"},
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert resp.status_code == 200

    entry = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.action == "password_changed",
        AuditLogEntry.actor_user_id == user.id,
    ).first()
    assert entry is not None
    assert entry.target_type == "user"
    assert entry.target_id == user.id

    # old token should now be revoked
    resp2 = client.put(
        "/change-password",
        json={"current_password": "newpass456", "new_password": "newpass456"},
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert resp2.status_code == 401


def test_kyc_status_changed_is_logged_with_after_detail(client, db_session):
    admin = make_user(db_session, "kycadmin1", account_type="admin")
    target = make_user(db_session, "kyctarget1")

    resp = client.put(
        f"/users/{target.id}/kyc-status",
        params={"status": "verified"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200

    entry = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.action == "kyc_status_changed",
        AuditLogEntry.target_id == target.id,
    ).first()
    assert entry is not None
    assert entry.actor_user_id == admin.id
    assert entry.target_type == "user"
    assert "verified" in entry.detail


def test_evidence_verify_is_logged(client, db_session):
    admin = make_user(db_session, "evadmin1", account_type="admin")
    owner = make_user(db_session, "evowner1")
    evidence = Evidence(
        user_id=owner.id,
        listing_id=None,
        transaction_id=None,
        ownership_record_id=None,
        evidence_type="cap_table",
        description="Test evidence",
        file_reference=None,
        file_hash=None,
        verification_status="pending",
        source_reference=None,
    )
    db_session.add(evidence)
    db_session.commit()
    db_session.refresh(evidence)

    resp = client.put(
        f"/evidence/{evidence.id}/verify",
        params={"status": "verified"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200

    entry = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.action == "evidence_verified",
        AuditLogEntry.target_id == evidence.id,
    ).first()
    assert entry is not None
    assert entry.actor_user_id == admin.id
    assert entry.target_type == "evidence"


def test_compliance_rule_update_is_logged(client, db_session):
    admin = make_user(db_session, "ruleadmin1", account_type="admin")
    rule = ComplianceRule(
        buyer_jurisdiction="United States",
        issuer_jurisdiction=None,
        asset_type="Private Shares",
        investor_classification="accredited",
        rule_code="TEST-RULE-001",
        description="Original description",
        fact_type="eligibility_verified",
        fact_validity_days=None,
        requirement="verified",
        decision_if_unmet="blocked",
        requires_human_review=True,
        active=True,
        source_reference="test",
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    resp = client.put(
        f"/compliance-rules/{rule.id}",
        json={"description": "Updated description"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200

    entry = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.action == "compliance_rule_updated",
        AuditLogEntry.target_id == rule.id,
    ).first()
    assert entry is not None
    assert entry.actor_user_id == admin.id
    assert entry.target_type == "compliance_rule"
    assert "description" in entry.detail
