"""
Tests for the evidence file upload/download endpoints (Batch B, group 3
item 7), 2026-09-24 - closes M23's real gap: file_reference/file_hash on
POST /evidence were caller-typed strings the platform never verified, so
a client could claim any string as a file's "hash" without ever sending
the actual bytes.

POST /evidence/{id}/upload-file writes real bytes to local disk and
computes the real SHA-256 hash itself, server-side; GET /evidence/{id}/file
serves the real bytes back. Every test here monkeypatches UPLOAD_DIR to a
pytest tmp_path, so nothing ever touches the real uploads/ directory on
disk or risks colliding with a real evidence id.

Written against the REAL ~/KEVO implementation.
"""
import os
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

import hashlib
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, User as UserModel, Evidence
import app as app_module
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


@pytest.fixture(autouse=True)
def patched_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path / "evidence_uploads"))


def auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def make_user(db, suffix="1", account_type="participant"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"evidenceupload{suffix}-{id(object())}@example.com",
        role="buyer",
        account_type=account_type,
        hashed_password=hash_password("originalpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_evidence(db, user, verification_status="pending"):
    evidence = Evidence(
        user_id=user.id,
        listing_id=None,
        transaction_id=None,
        ownership_record_id=None,
        evidence_type="cap_table",
        description="Test evidence",
        file_reference=None,
        file_hash=None,
        verification_status=verification_status,
        source_reference=None,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


def test_owner_can_upload_file_and_hash_is_server_computed(client, db_session):
    user = make_user(db_session, "owner1")
    evidence = make_evidence(db_session, user)

    file_content = b"this is a real test file's bytes"
    expected_hash = hashlib.sha256(file_content).hexdigest()

    resp = client.post(
        f"/evidence/{evidence.id}/upload-file",
        headers=auth_headers(user),
        files={"file": ("test.txt", file_content, "text/plain")},
    )

    assert resp.status_code == 200
    data = resp.json()["evidence"]
    assert data["file_hash"] == expected_hash
    assert data["file_reference"] == f"/evidence/{evidence.id}/file"

    db_session.refresh(evidence)
    assert evidence.file_hash == expected_hash


def test_non_owner_non_admin_gets_403(client, db_session):
    owner = make_user(db_session, "owner2")
    stranger = make_user(db_session, "stranger2")
    evidence = make_evidence(db_session, owner)

    resp = client.post(
        f"/evidence/{evidence.id}/upload-file",
        headers=auth_headers(stranger),
        files={"file": ("test.txt", b"data", "text/plain")},
    )
    assert resp.status_code == 403


def test_admin_can_upload_to_others_evidence(client, db_session):
    owner = make_user(db_session, "owner3")
    admin = make_user(db_session, "admin3", account_type="admin")
    evidence = make_evidence(db_session, owner)

    resp = client.post(
        f"/evidence/{evidence.id}/upload-file",
        headers=auth_headers(admin),
        files={"file": ("test.txt", b"admin uploaded data", "text/plain")},
    )
    assert resp.status_code == 200


def test_empty_file_rejected_400(client, db_session):
    user = make_user(db_session, "owner4")
    evidence = make_evidence(db_session, user)

    resp = client.post(
        f"/evidence/{evidence.id}/upload-file",
        headers=auth_headers(user),
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert resp.status_code == 400


def test_oversized_file_rejected_400(client, db_session, monkeypatch):
    user = make_user(db_session, "owner5")
    evidence = make_evidence(db_session, user)

    monkeypatch.setattr(app_module, "MAX_EVIDENCE_UPLOAD_BYTES", 10)

    resp = client.post(
        f"/evidence/{evidence.id}/upload-file",
        headers=auth_headers(user),
        files={"file": ("big.txt", b"this is definitely more than ten bytes", "text/plain")},
    )
    assert resp.status_code == 400


def test_cannot_upload_to_already_verified_evidence(client, db_session):
    user = make_user(db_session, "owner6")
    evidence = make_evidence(db_session, user, verification_status="verified")

    resp = client.post(
        f"/evidence/{evidence.id}/upload-file",
        headers=auth_headers(user),
        files={"file": ("test.txt", b"data", "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_to_nonexistent_evidence_404(client, db_session):
    user = make_user(db_session, "owner7")

    resp = client.post(
        "/evidence/999999/upload-file",
        headers=auth_headers(user),
        files={"file": ("test.txt", b"data", "text/plain")},
    )
    assert resp.status_code == 404


def test_upload_requires_authentication(client, db_session):
    user = make_user(db_session, "owner8")
    evidence = make_evidence(db_session, user)

    resp = client.post(
        f"/evidence/{evidence.id}/upload-file",
        files={"file": ("test.txt", b"data", "text/plain")},
    )
    assert resp.status_code == 401


def test_download_round_trip_bytes_match_exactly(client, db_session):
    user = make_user(db_session, "owner9")
    evidence = make_evidence(db_session, user)

    file_content = b"round trip integrity check \x00\x01\x02 binary-safe"
    client.post(
        f"/evidence/{evidence.id}/upload-file",
        headers=auth_headers(user),
        files={"file": ("test.bin", file_content, "application/octet-stream")},
    )

    resp = client.get(f"/evidence/{evidence.id}/file", headers=auth_headers(user))
    assert resp.status_code == 200
    assert resp.content == file_content


def test_download_non_owner_non_admin_gets_403(client, db_session):
    owner = make_user(db_session, "owner10")
    stranger = make_user(db_session, "stranger10")
    evidence = make_evidence(db_session, owner)

    client.post(
        f"/evidence/{evidence.id}/upload-file",
        headers=auth_headers(owner),
        files={"file": ("test.txt", b"data", "text/plain")},
    )

    resp = client.get(f"/evidence/{evidence.id}/file", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_download_admin_can_view_others_file(client, db_session):
    owner = make_user(db_session, "owner11")
    admin = make_user(db_session, "admin11", account_type="admin")
    evidence = make_evidence(db_session, owner)

    client.post(
        f"/evidence/{evidence.id}/upload-file",
        headers=auth_headers(owner),
        files={"file": ("test.txt", b"admin can see this", "text/plain")},
    )

    resp = client.get(f"/evidence/{evidence.id}/file", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.content == b"admin can see this"


def test_download_no_file_uploaded_yet_404(client, db_session):
    user = make_user(db_session, "owner12")
    evidence = make_evidence(db_session, user)

    resp = client.get(f"/evidence/{evidence.id}/file", headers=auth_headers(user))
    assert resp.status_code == 404


def test_download_nonexistent_evidence_404(client, db_session):
    user = make_user(db_session, "owner13")

    resp = client.get("/evidence/999999/file", headers=auth_headers(user))
    assert resp.status_code == 404


def test_download_requires_authentication(client, db_session):
    user = make_user(db_session, "owner14")
    evidence = make_evidence(db_session, user)

    resp = client.get(f"/evidence/{evidence.id}/file")
    assert resp.status_code == 401


def test_second_upload_before_verification_replaces_content(client, db_session):
    user = make_user(db_session, "owner15")
    evidence = make_evidence(db_session, user)

    client.post(
        f"/evidence/{evidence.id}/upload-file",
        headers=auth_headers(user),
        files={"file": ("first.txt", b"first version", "text/plain")},
    )
    resp2 = client.post(
        f"/evidence/{evidence.id}/upload-file",
        headers=auth_headers(user),
        files={"file": ("second.txt", b"second version replaces it", "text/plain")},
    )
    assert resp2.status_code == 200

    resp = client.get(f"/evidence/{evidence.id}/file", headers=auth_headers(user))
    assert resp.status_code == 200
    assert resp.content == b"second version replaces it"
