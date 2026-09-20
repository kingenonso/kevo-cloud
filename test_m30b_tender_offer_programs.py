"""
Tests for M30B's first slice (2026-09-20): Company-Sponsored Tender Offer
Program, admin-administered only.

KEVO has no company/issuer login-capable actor - an admin creates and
manages a tender offer program on a real company's behalf (price, window,
eligibility already agreed to outside the platform), and holders with a
verified ownership record in that company can elect to participate.
Admin finalizes each election, recording the company's own real
accept/decline decision and share count - KEVO never computes or suggests
an allocation. Canada is deliberately excluded (see
claude/kevo-m30b-tender-offer-program-research-and-audit.md).
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

from models import (
    Base, User as UserModel, OwnershipRecord, TenderOfferProgram, TenderOfferElection,
)
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
        email=f"m30buser{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status="not_started",
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_ownership_record(db, seller, company="Acme Inc", quantity=1000, verification_status="verified"):
    record = OwnershipRecord(
        seller_id=seller.id, company=company, asset_type="Private Shares",
        quantity=quantity, verification_status=verification_status,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def make_program(db, company="Acme Inc", jurisdiction="United States", price_per_share=10.0,
                  status="open", opens_delta_hours=-1, closes_delta_hours=24):
    now = datetime.utcnow()
    program = TenderOfferProgram(
        company=company, jurisdiction=jurisdiction, price_per_share=price_per_share,
        opens_at=now + timedelta(hours=opens_delta_hours),
        closes_at=now + timedelta(hours=closes_delta_hours),
        status=status, created_at=now,
    )
    db.add(program)
    db.commit()
    db.refresh(program)
    return program


def make_election(db, program, ownership_record, holder, shares_offered=100, status="pending"):
    election = TenderOfferElection(
        program_id=program.id, ownership_record_id=ownership_record.id, holder_id=holder.id,
        shares_offered=shares_offered, status=status, created_at=datetime.utcnow(),
    )
    db.add(election)
    db.commit()
    db.refresh(election)
    return election

# ---------------------------------------------------------------------------
# POST /tender-offer-programs
# ---------------------------------------------------------------------------

def test_admin_can_create_program(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    opens = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    closes = (datetime.utcnow() + timedelta(hours=48)).isoformat()
    resp = client.post("/tender-offer-programs", params={
        "company": "Acme Inc",
        "jurisdiction": "United States",
        "price_per_share": 12.50,
        "opens_at": opens,
        "closes_at": closes,
        "source_reference": "Board resolution 2026-09-20",
    }, headers=auth_headers(admin))
    assert resp.status_code == 200
    data = resp.json()
    assert data["company"] == "Acme Inc"
    assert data["jurisdiction"] == "United States"
    assert float(data["price_per_share"]) == 12.50
    assert data["status"] == "open"
    assert data["source_reference"] == "Board resolution 2026-09-20"


def test_create_program_non_admin_forbidden(client, db_session):
    user = make_user(db_session, suffix="p1", account_type="participant")
    opens = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    closes = (datetime.utcnow() + timedelta(hours=48)).isoformat()
    resp = client.post("/tender-offer-programs", params={
        "company": "Acme Inc",
        "jurisdiction": "United States",
        "price_per_share": 12.50,
        "opens_at": opens,
        "closes_at": closes,
    }, headers=auth_headers(user))
    assert resp.status_code == 403


def test_create_program_canada_rejected(client, db_session):
    admin = make_user(db_session, suffix="a2", account_type="admin")
    opens = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    closes = (datetime.utcnow() + timedelta(hours=48)).isoformat()
    resp = client.post("/tender-offer-programs", params={
        "company": "Acme Inc",
        "jurisdiction": "Canada",
        "price_per_share": 12.50,
        "opens_at": opens,
        "closes_at": closes,
    }, headers=auth_headers(admin))
    assert resp.status_code == 400
    assert "canada" in resp.json()["detail"].lower()


def test_create_program_non_positive_price_rejected(client, db_session):
    admin = make_user(db_session, suffix="a3", account_type="admin")
    opens = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    closes = (datetime.utcnow() + timedelta(hours=48)).isoformat()
    resp = client.post("/tender-offer-programs", params={
        "company": "Acme Inc",
        "jurisdiction": "United States",
        "price_per_share": 0,
        "opens_at": opens,
        "closes_at": closes,
    }, headers=auth_headers(admin))
    assert resp.status_code == 400


def test_create_program_closes_before_opens_rejected(client, db_session):
    admin = make_user(db_session, suffix="a4", account_type="admin")
    opens = (datetime.utcnow() + timedelta(hours=48)).isoformat()
    closes = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    resp = client.post("/tender-offer-programs", params={
        "company": "Acme Inc",
        "jurisdiction": "United States",
        "price_per_share": 12.50,
        "opens_at": opens,
        "closes_at": closes,
    }, headers=auth_headers(admin))
    assert resp.status_code == 400


def test_create_program_unauthenticated_rejected(client):
    resp = client.post("/tender-offer-programs", params={
        "company": "Acme Inc",
        "jurisdiction": "United States",
        "price_per_share": 12.50,
        "opens_at": datetime.utcnow().isoformat(),
        "closes_at": (datetime.utcnow() + timedelta(hours=48)).isoformat(),
    })
    assert resp.status_code == 401

# ---------------------------------------------------------------------------
# GET /tender-offer-programs
# ---------------------------------------------------------------------------

def test_admin_sees_all_programs(client, db_session):
    admin = make_user(db_session, suffix="a5", account_type="admin")
    make_program(db_session, company="Acme Inc")
    make_program(db_session, company="Beta Corp")
    resp = client.get("/tender-offer-programs", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_participant_sees_only_eligible_programs(client, db_session):
    seller = make_user(db_session, suffix="s1", role="seller")
    make_ownership_record(db_session, seller, company="Acme Inc")
    make_program(db_session, company="Acme Inc")
    make_program(db_session, company="Beta Corp")
    resp = client.get("/tender-offer-programs", headers=auth_headers(seller))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["company"] == "Acme Inc"


def test_participant_with_no_verified_holdings_sees_empty_list(client, db_session):
    seller = make_user(db_session, suffix="s2", role="seller")
    make_program(db_session, company="Acme Inc")
    resp = client.get("/tender-offer-programs", headers=auth_headers(seller))
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_programs_unauthenticated_rejected(client):
    resp = client.get("/tender-offer-programs")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /tender-offer-programs/{program_id}
# ---------------------------------------------------------------------------

def test_admin_can_get_any_program(client, db_session):
    admin = make_user(db_session, suffix="a6", account_type="admin")
    program = make_program(db_session, company="Acme Inc")
    resp = client.get(f"/tender-offer-programs/{program.id}", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["company"] == "Acme Inc"


def test_eligible_participant_can_get_program(client, db_session):
    seller = make_user(db_session, suffix="s3", role="seller")
    make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    resp = client.get(f"/tender-offer-programs/{program.id}", headers=auth_headers(seller))
    assert resp.status_code == 200


def test_ineligible_participant_forbidden_from_program(client, db_session):
    seller = make_user(db_session, suffix="s4", role="seller")
    program = make_program(db_session, company="Acme Inc")
    resp = client.get(f"/tender-offer-programs/{program.id}", headers=auth_headers(seller))
    assert resp.status_code == 403


def test_get_program_not_found(client, db_session):
    admin = make_user(db_session, suffix="a7", account_type="admin")
    resp = client.get("/tender-offer-programs/999999", headers=auth_headers(admin))
    assert resp.status_code == 404


def test_get_program_unauthenticated_rejected(client, db_session):
    program = make_program(db_session, company="Acme Inc")
    resp = client.get(f"/tender-offer-programs/{program.id}")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /tender-offer-programs/{program_id}/close
# ---------------------------------------------------------------------------

def test_admin_can_close_open_program(client, db_session):
    admin = make_user(db_session, suffix="a8", account_type="admin")
    program = make_program(db_session, company="Acme Inc", status="open")
    resp = client.put(f"/tender-offer-programs/{program.id}/close", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"


def test_close_program_non_admin_forbidden(client, db_session):
    seller = make_user(db_session, suffix="s5", role="seller")
    program = make_program(db_session, company="Acme Inc", status="open")
    resp = client.put(f"/tender-offer-programs/{program.id}/close", headers=auth_headers(seller))
    assert resp.status_code == 403


def test_close_already_closed_program_rejected(client, db_session):
    admin = make_user(db_session, suffix="a9", account_type="admin")
    program = make_program(db_session, company="Acme Inc", status="closed")
    resp = client.put(f"/tender-offer-programs/{program.id}/close", headers=auth_headers(admin))
    assert resp.status_code == 400


def test_close_program_not_found(client, db_session):
    admin = make_user(db_session, suffix="a10", account_type="admin")
    resp = client.put("/tender-offer-programs/999999/close", headers=auth_headers(admin))
    assert resp.status_code == 404


def test_close_program_unauthenticated_rejected(client, db_session):
    program = make_program(db_session, company="Acme Inc", status="open")
    resp = client.put(f"/tender-offer-programs/{program.id}/close")
    assert resp.status_code == 401

# ---------------------------------------------------------------------------
# POST /tender-offer-elections
# ---------------------------------------------------------------------------

def test_holder_can_create_election(client, db_session):
    seller = make_user(db_session, suffix="e1", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc", quantity=500)
    program = make_program(db_session, company="Acme Inc")
    resp = client.post("/tender-offer-elections", params={
        "program_id": program.id,
        "ownership_record_id": record.id,
        "shares_offered": 200,
    }, headers=auth_headers(seller))
    assert resp.status_code == 200
    data = resp.json()
    assert data["program_id"] == program.id
    assert data["shares_offered"] == 200
    assert data["status"] == "pending"


def test_create_election_program_not_found(client, db_session):
    seller = make_user(db_session, suffix="e2", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    resp = client.post("/tender-offer-elections", params={
        "program_id": 999999,
        "ownership_record_id": record.id,
        "shares_offered": 100,
    }, headers=auth_headers(seller))
    assert resp.status_code == 404


def test_create_election_program_not_open_rejected(client, db_session):
    seller = make_user(db_session, suffix="e3", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc", status="closed")
    resp = client.post("/tender-offer-elections", params={
        "program_id": program.id,
        "ownership_record_id": record.id,
        "shares_offered": 100,
    }, headers=auth_headers(seller))
    assert resp.status_code == 400


def test_create_election_window_not_yet_open_rejected(client, db_session):
    seller = make_user(db_session, suffix="e4", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc", opens_delta_hours=5, closes_delta_hours=24)
    resp = client.post("/tender-offer-elections", params={
        "program_id": program.id,
        "ownership_record_id": record.id,
        "shares_offered": 100,
    }, headers=auth_headers(seller))
    assert resp.status_code == 400


def test_create_election_window_already_past_rejected(client, db_session):
    seller = make_user(db_session, suffix="e5", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc", opens_delta_hours=-48, closes_delta_hours=-1)
    resp = client.post("/tender-offer-elections", params={
        "program_id": program.id,
        "ownership_record_id": record.id,
        "shares_offered": 100,
    }, headers=auth_headers(seller))
    assert resp.status_code == 400


def test_create_election_ownership_record_not_found(client, db_session):
    seller = make_user(db_session, suffix="e6", role="seller")
    program = make_program(db_session, company="Acme Inc")
    resp = client.post("/tender-offer-elections", params={
        "program_id": program.id,
        "ownership_record_id": 999999,
        "shares_offered": 100,
    }, headers=auth_headers(seller))
    assert resp.status_code == 404


def test_create_election_not_own_ownership_record_forbidden(client, db_session):
    seller = make_user(db_session, suffix="e7", role="seller")
    other_seller = make_user(db_session, suffix="e8", role="seller")
    record = make_ownership_record(db_session, other_seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    resp = client.post("/tender-offer-elections", params={
        "program_id": program.id,
        "ownership_record_id": record.id,
        "shares_offered": 100,
    }, headers=auth_headers(seller))
    assert resp.status_code == 403


def test_create_election_unverified_ownership_record_rejected(client, db_session):
    seller = make_user(db_session, suffix="e9", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc", verification_status="pending")
    program = make_program(db_session, company="Acme Inc")
    resp = client.post("/tender-offer-elections", params={
        "program_id": program.id,
        "ownership_record_id": record.id,
        "shares_offered": 100,
    }, headers=auth_headers(seller))
    assert resp.status_code == 400


def test_create_election_company_mismatch_rejected(client, db_session):
    seller = make_user(db_session, suffix="e10", role="seller")
    record = make_ownership_record(db_session, seller, company="Different Co")
    program = make_program(db_session, company="Acme Inc")
    resp = client.post("/tender-offer-elections", params={
        "program_id": program.id,
        "ownership_record_id": record.id,
        "shares_offered": 100,
    }, headers=auth_headers(seller))
    assert resp.status_code == 400


def test_create_election_non_positive_shares_rejected(client, db_session):
    seller = make_user(db_session, suffix="e11", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    resp = client.post("/tender-offer-elections", params={
        "program_id": program.id,
        "ownership_record_id": record.id,
        "shares_offered": 0,
    }, headers=auth_headers(seller))
    assert resp.status_code == 400


def test_create_election_shares_exceed_quantity_rejected(client, db_session):
    seller = make_user(db_session, suffix="e12", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc", quantity=100)
    program = make_program(db_session, company="Acme Inc")
    resp = client.post("/tender-offer-elections", params={
        "program_id": program.id,
        "ownership_record_id": record.id,
        "shares_offered": 101,
    }, headers=auth_headers(seller))
    assert resp.status_code == 400


def test_create_election_unauthenticated_rejected(client, db_session):
    seller = make_user(db_session, suffix="e13", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    resp = client.post("/tender-offer-elections", params={
        "program_id": program.id,
        "ownership_record_id": record.id,
        "shares_offered": 100,
    })
    assert resp.status_code == 401

# ---------------------------------------------------------------------------
# PUT /tender-offer-elections/{election_id}/withdraw
# ---------------------------------------------------------------------------

def test_holder_can_withdraw_pending_election(client, db_session):
    seller = make_user(db_session, suffix="w1", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller)
    resp = client.put(f"/tender-offer-elections/{election.id}/withdraw", headers=auth_headers(seller))
    assert resp.status_code == 200
    assert resp.json()["status"] == "withdrawn"


def test_withdraw_election_non_holder_forbidden(client, db_session):
    seller = make_user(db_session, suffix="w2", role="seller")
    other = make_user(db_session, suffix="w3", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller)
    resp = client.put(f"/tender-offer-elections/{election.id}/withdraw", headers=auth_headers(other))
    assert resp.status_code == 403


def test_withdraw_non_pending_election_rejected(client, db_session):
    seller = make_user(db_session, suffix="w4", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller, status="accepted")
    resp = client.put(f"/tender-offer-elections/{election.id}/withdraw", headers=auth_headers(seller))
    assert resp.status_code == 400


def test_withdraw_election_not_found(client, db_session):
    seller = make_user(db_session, suffix="w5", role="seller")
    resp = client.put("/tender-offer-elections/999999/withdraw", headers=auth_headers(seller))
    assert resp.status_code == 404


def test_withdraw_election_unauthenticated_rejected(client, db_session):
    seller = make_user(db_session, suffix="w6", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller)
    resp = client.put(f"/tender-offer-elections/{election.id}/withdraw")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /tender-offer-elections/{election_id}/finalize
# ---------------------------------------------------------------------------

def test_admin_can_accept_election(client, db_session):
    admin = make_user(db_session, suffix="f1", account_type="admin")
    seller = make_user(db_session, suffix="f2", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller, shares_offered=100)
    resp = client.put(f"/tender-offer-elections/{election.id}/finalize", params={
        "accepted": True,
        "shares_accepted": 80,
    }, headers=auth_headers(admin))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["shares_accepted"] == 80


def test_admin_can_decline_election(client, db_session):
    admin = make_user(db_session, suffix="f3", account_type="admin")
    seller = make_user(db_session, suffix="f4", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller)
    resp = client.put(f"/tender-offer-elections/{election.id}/finalize", params={
        "accepted": False,
    }, headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["status"] == "declined"


def test_finalize_election_non_admin_forbidden(client, db_session):
    seller = make_user(db_session, suffix="f5", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller)
    resp = client.put(f"/tender-offer-elections/{election.id}/finalize", params={
        "accepted": True,
        "shares_accepted": 50,
    }, headers=auth_headers(seller))
    assert resp.status_code == 403


def test_finalize_non_pending_election_rejected(client, db_session):
    admin = make_user(db_session, suffix="f6", account_type="admin")
    seller = make_user(db_session, suffix="f7", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller, status="withdrawn")
    resp = client.put(f"/tender-offer-elections/{election.id}/finalize", params={
        "accepted": False,
    }, headers=auth_headers(admin))
    assert resp.status_code == 400


def test_finalize_accept_without_shares_accepted_rejected(client, db_session):
    admin = make_user(db_session, suffix="f8", account_type="admin")
    seller = make_user(db_session, suffix="f9", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller)
    resp = client.put(f"/tender-offer-elections/{election.id}/finalize", params={
        "accepted": True,
    }, headers=auth_headers(admin))
    assert resp.status_code == 400


def test_finalize_accept_non_positive_shares_accepted_rejected(client, db_session):
    admin = make_user(db_session, suffix="f10", account_type="admin")
    seller = make_user(db_session, suffix="f11", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller)
    resp = client.put(f"/tender-offer-elections/{election.id}/finalize", params={
        "accepted": True,
        "shares_accepted": 0,
    }, headers=auth_headers(admin))
    assert resp.status_code == 400


def test_finalize_accept_shares_exceed_offered_rejected(client, db_session):
    admin = make_user(db_session, suffix="f12", account_type="admin")
    seller = make_user(db_session, suffix="f13", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller, shares_offered=100)
    resp = client.put(f"/tender-offer-elections/{election.id}/finalize", params={
        "accepted": True,
        "shares_accepted": 101,
    }, headers=auth_headers(admin))
    assert resp.status_code == 400


def test_finalize_election_not_found(client, db_session):
    admin = make_user(db_session, suffix="f14", account_type="admin")
    resp = client.put("/tender-offer-elections/999999/finalize", params={
        "accepted": False,
    }, headers=auth_headers(admin))
    assert resp.status_code == 404


def test_finalize_election_unauthenticated_rejected(client, db_session):
    seller = make_user(db_session, suffix="f15", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller)
    resp = client.put(f"/tender-offer-elections/{election.id}/finalize", params={
        "accepted": False,
    })
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /tender-offer-elections
# ---------------------------------------------------------------------------

def test_admin_sees_all_elections(client, db_session):
    admin = make_user(db_session, suffix="l1", account_type="admin")
    seller = make_user(db_session, suffix="l2", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    make_election(db_session, program, record, seller)
    make_election(db_session, program, record, seller)
    resp = client.get("/tender-offer-elections", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_participant_sees_only_own_elections(client, db_session):
    seller = make_user(db_session, suffix="l3", role="seller")
    other = make_user(db_session, suffix="l4", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    other_record = make_ownership_record(db_session, other, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    make_election(db_session, program, record, seller)
    make_election(db_session, program, other_record, other)
    resp = client.get("/tender-offer-elections", headers=auth_headers(seller))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["holder_id"] == seller.id


def test_list_elections_unauthenticated_rejected(client):
    resp = client.get("/tender-offer-elections")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /tender-offer-elections/{election_id}
# ---------------------------------------------------------------------------

def test_admin_can_get_any_election(client, db_session):
    admin = make_user(db_session, suffix="g1", account_type="admin")
    seller = make_user(db_session, suffix="g2", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller)
    resp = client.get(f"/tender-offer-elections/{election.id}", headers=auth_headers(admin))
    assert resp.status_code == 200


def test_holder_can_get_own_election(client, db_session):
    seller = make_user(db_session, suffix="g3", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller)
    resp = client.get(f"/tender-offer-elections/{election.id}", headers=auth_headers(seller))
    assert resp.status_code == 200


def test_other_participant_forbidden_from_election(client, db_session):
    seller = make_user(db_session, suffix="g4", role="seller")
    other = make_user(db_session, suffix="g5", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller)
    resp = client.get(f"/tender-offer-elections/{election.id}", headers=auth_headers(other))
    assert resp.status_code == 403


def test_get_election_not_found(client, db_session):
    admin = make_user(db_session, suffix="g6", account_type="admin")
    resp = client.get("/tender-offer-elections/999999", headers=auth_headers(admin))
    assert resp.status_code == 404


def test_get_election_unauthenticated_rejected(client, db_session):
    seller = make_user(db_session, suffix="g7", role="seller")
    record = make_ownership_record(db_session, seller, company="Acme Inc")
    program = make_program(db_session, company="Acme Inc")
    election = make_election(db_session, program, record, seller)
    resp = client.get(f"/tender-offer-elections/{election.id}")
    assert resp.status_code == 401
