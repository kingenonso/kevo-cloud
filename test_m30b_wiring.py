"""
Tests for M30B's gap-closure wiring (2026-10-22): transfer review, the
optional/informational ROFR review, settlement tracking
(TenderOfferSettlement), and recurring open/close schedule support
(POST /tender-offer-programs/{id}/next-cycle).

Written against the real ~/KEVO implementation, same fixture pattern as
test_m30b_tender_offer_programs.py (the first-slice test file).
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
    Base, User as UserModel, OwnershipRecord, TenderOfferProgram,
    TenderOfferElection, TenderOfferSettlement,
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


def make_user(db, suffix="1", role="buyer", account_type="participant", kyc_status="verified"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"m30bwiring{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
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
                  status="open", opens_delta_hours=-1, closes_delta_hours=24,
                  is_recurring=False, recurrence_interval_days=None):
    now = datetime.utcnow()
    program = TenderOfferProgram(
        company=company, jurisdiction=jurisdiction, price_per_share=price_per_share,
        opens_at=now + timedelta(hours=opens_delta_hours),
        closes_at=now + timedelta(hours=closes_delta_hours),
        status=status, created_at=now,
        is_recurring=is_recurring, recurrence_interval_days=recurrence_interval_days,
    )
    db.add(program)
    db.commit()
    db.refresh(program)
    return program


def make_election(db, program, ownership_record, holder, shares_offered=100, shares_accepted=None,
                   status="pending", transfer_reviewed=False):
    election = TenderOfferElection(
        program_id=program.id, ownership_record_id=ownership_record.id, holder_id=holder.id,
        shares_offered=shares_offered, shares_accepted=shares_accepted, status=status,
        created_at=datetime.utcnow(), transfer_reviewed=transfer_reviewed,
    )
    db.add(election)
    db.commit()
    db.refresh(election)
    return election


def make_settlement(db, election, **kwargs):
    settlement = TenderOfferSettlement(
        election_id=election.id, status=kwargs.get("status", "pending"),
        funds_received=kwargs.get("funds_received", False),
        funds_received_at=kwargs.get("funds_received_at"),
        shares_confirmed_transferable=kwargs.get("shares_confirmed_transferable", False),
        shares_confirmed_transferable_at=kwargs.get("shares_confirmed_transferable_at"),
        funds_released=kwargs.get("funds_released", False),
        funds_released_at=kwargs.get("funds_released_at"),
        created_at=datetime.utcnow(),
    )
    db.add(settlement)
    db.commit()
    db.refresh(settlement)
    return settlement


# ---------------------------------------------------------------------------
# PUT /tender-offer-elections/{id}/transfer-review
# ---------------------------------------------------------------------------

def test_admin_can_transfer_review_accepted_election(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    holder = make_user(db_session, suffix="h1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(db_session, program, record, holder, shares_accepted=100, status="accepted")

    resp = client.put(
        f"/tender-offer-elections/{election.id}/transfer-review",
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["transfer_reviewed"] is True
    assert data["transfer_reviewed_at"] is not None


def test_transfer_review_requires_admin(client, db_session):
    holder = make_user(db_session, suffix="h1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(db_session, program, record, holder, shares_accepted=100, status="accepted")

    resp = client.put(
        f"/tender-offer-elections/{election.id}/transfer-review",
        headers=auth_headers(holder),
    )

    assert resp.status_code == 403


def test_transfer_review_requires_accepted_status(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    holder = make_user(db_session, suffix="h1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(db_session, program, record, holder, status="pending")

    resp = client.put(
        f"/tender-offer-elections/{election.id}/transfer-review",
        headers=auth_headers(admin),
    )

    assert resp.status_code == 400


def test_transfer_review_404_when_missing(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")

    resp = client.put(
        "/tender-offer-elections/999999/transfer-review",
        headers=auth_headers(admin),
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /tender-offer-elections/{id}/rofr-review (optional, informational)
# ---------------------------------------------------------------------------

def test_admin_can_record_rofr_not_applicable(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    holder = make_user(db_session, suffix="h1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(db_session, program, record, holder, shares_accepted=100, status="accepted")

    resp = client.put(
        f"/tender-offer-elections/{election.id}/rofr-review",
        params={"cleared": True, "notes": "Shareholders' agreement carves out issuer repurchases from ROFR"},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["rofr_cleared"] is True
    assert "carves out" in data["rofr_notes"]


def test_rofr_review_requires_admin(client, db_session):
    holder = make_user(db_session, suffix="h1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(db_session, program, record, holder, shares_accepted=100, status="accepted")

    resp = client.put(
        f"/tender-offer-elections/{election.id}/rofr-review",
        params={"cleared": True},
        headers=auth_headers(holder),
    )

    assert resp.status_code == 403


def test_settlement_does_not_require_rofr_review(client, db_session):
    """
    ROFR review is deliberately informational, not a gate - a settlement
    can be created with rofr_cleared left untouched (null), since most
    buybacks never need it reviewed at all.
    """
    admin = make_user(db_session, suffix="a1", account_type="admin")
    holder = make_user(db_session, suffix="h1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(
        db_session, program, record, holder, shares_accepted=100,
        status="accepted", transfer_reviewed=True,
    )
    assert election.rofr_cleared is None

    resp = client.post(
        "/tender-offer-settlements",
        params={"election_id": election.id},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /tender-offer-settlements
# ---------------------------------------------------------------------------

def test_admin_can_create_settlement_for_reviewed_accepted_election(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    holder = make_user(db_session, suffix="h1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(
        db_session, program, record, holder, shares_accepted=100,
        status="accepted", transfer_reviewed=True,
    )

    resp = client.post(
        "/tender-offer-settlements",
        params={"election_id": election.id},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["election_id"] == election.id
    assert data["status"] == "pending"
    assert data["funds_received"] is False


def test_create_settlement_requires_admin(client, db_session):
    holder = make_user(db_session, suffix="h1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(
        db_session, program, record, holder, shares_accepted=100,
        status="accepted", transfer_reviewed=True,
    )

    resp = client.post(
        "/tender-offer-settlements",
        params={"election_id": election.id},
        headers=auth_headers(holder),
    )

    assert resp.status_code == 403


def test_create_settlement_requires_accepted_election(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    holder = make_user(db_session, suffix="h1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(db_session, program, record, holder, status="pending")

    resp = client.post(
        "/tender-offer-settlements",
        params={"election_id": election.id},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 400


def test_create_settlement_requires_transfer_review_first(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    holder = make_user(db_session, suffix="h1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(
        db_session, program, record, holder, shares_accepted=100,
        status="accepted", transfer_reviewed=False,
    )

    resp = client.post(
        "/tender-offer-settlements",
        params={"election_id": election.id},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 400
    assert "transfer-reviewed" in resp.json()["detail"]


def test_cannot_create_duplicate_settlement_for_same_election(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    holder = make_user(db_session, suffix="h1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(
        db_session, program, record, holder, shares_accepted=100,
        status="accepted", transfer_reviewed=True,
    )
    make_settlement(db_session, election)

    resp = client.post(
        "/tender-offer-settlements",
        params={"election_id": election.id},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"]


def test_create_settlement_404_for_missing_election(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")

    resp = client.post(
        "/tender-offer-settlements",
        params={"election_id": 999999},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /tender-offer-settlements, GET /tender-offer-settlements/{id}
# ---------------------------------------------------------------------------

def test_admin_sees_all_settlements(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    holder1 = make_user(db_session, suffix="h1")
    holder2 = make_user(db_session, suffix="h2")
    program = make_program(db_session)
    record1 = make_ownership_record(db_session, holder1)
    record2 = make_ownership_record(db_session, holder2)
    election1 = make_election(db_session, program, record1, holder1, shares_accepted=50, status="accepted")
    election2 = make_election(db_session, program, record2, holder2, shares_accepted=75, status="accepted")
    make_settlement(db_session, election1)
    make_settlement(db_session, election2)

    resp = client.get("/tender-offer-settlements", headers=auth_headers(admin))

    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_holder_sees_only_own_settlement(client, db_session):
    holder1 = make_user(db_session, suffix="h1")
    holder2 = make_user(db_session, suffix="h2")
    program = make_program(db_session)
    record1 = make_ownership_record(db_session, holder1)
    record2 = make_ownership_record(db_session, holder2)
    election1 = make_election(db_session, program, record1, holder1, shares_accepted=50, status="accepted")
    election2 = make_election(db_session, program, record2, holder2, shares_accepted=75, status="accepted")
    make_settlement(db_session, election1)
    settlement2 = make_settlement(db_session, election2)

    resp = client.get("/tender-offer-settlements", headers=auth_headers(holder2))

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == settlement2.id


def test_get_settlement_by_id_403_for_non_party(client, db_session):
    holder = make_user(db_session, suffix="h1")
    stranger = make_user(db_session, suffix="s1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(db_session, program, record, holder, shares_accepted=50, status="accepted")
    settlement = make_settlement(db_session, election)

    resp = client.get(f"/tender-offer-settlements/{settlement.id}", headers=auth_headers(stranger))

    assert resp.status_code == 403


def test_get_settlement_404_when_missing(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")

    resp = client.get("/tender-offer-settlements/999999", headers=auth_headers(admin))

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT .../confirm-funds-received, confirm-shares-transferable, release-funds
# ---------------------------------------------------------------------------

def test_full_settlement_sequence_to_release(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    holder = make_user(db_session, suffix="h1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(db_session, program, record, holder, shares_accepted=100, status="accepted")
    settlement = make_settlement(db_session, election)

    r1 = client.put(
        f"/tender-offer-settlements/{settlement.id}/confirm-funds-received",
        params={"notes": "Wire confirmed by treasury"},
        headers=auth_headers(admin),
    )
    assert r1.status_code == 200
    assert r1.json()["funds_received"] is True
    assert r1.json()["status"] == "in_progress"

    r2 = client.put(
        f"/tender-offer-settlements/{settlement.id}/confirm-shares-transferable",
        headers=auth_headers(admin),
    )
    assert r2.status_code == 200
    assert r2.json()["shares_confirmed_transferable"] is True

    r3 = client.put(
        f"/tender-offer-settlements/{settlement.id}/release-funds",
        headers=auth_headers(admin),
    )
    assert r3.status_code == 200
    assert r3.json()["funds_released"] is True
    assert r3.json()["status"] == "completed"


def test_cannot_release_funds_before_both_confirmations(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    holder = make_user(db_session, suffix="h1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(db_session, program, record, holder, shares_accepted=100, status="accepted")
    settlement = make_settlement(db_session, election, funds_received=True)

    resp = client.put(
        f"/tender-offer-settlements/{settlement.id}/release-funds",
        headers=auth_headers(admin),
    )

    assert resp.status_code == 400


def test_confirm_funds_received_requires_admin(client, db_session):
    holder = make_user(db_session, suffix="h1")
    program = make_program(db_session)
    record = make_ownership_record(db_session, holder)
    election = make_election(db_session, program, record, holder, shares_accepted=100, status="accepted")
    settlement = make_settlement(db_session, election)

    resp = client.put(
        f"/tender-offer-settlements/{settlement.id}/confirm-funds-received",
        headers=auth_headers(holder),
    )

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /tender-offer-programs with is_recurring / recurrence_interval_days
# ---------------------------------------------------------------------------

def test_admin_can_create_recurring_program(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    opens = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    closes = (datetime.utcnow() + timedelta(hours=48)).isoformat()

    resp = client.post("/tender-offer-programs", params={
        "company": "Acme Inc",
        "jurisdiction": "United States",
        "price_per_share": 12.50,
        "opens_at": opens,
        "closes_at": closes,
        "is_recurring": True,
        "recurrence_interval_days": 182,
    }, headers=auth_headers(admin))

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_recurring"] is True
    assert data["recurrence_interval_days"] == 182


def test_recurring_program_requires_interval(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    opens = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    closes = (datetime.utcnow() + timedelta(hours=48)).isoformat()

    resp = client.post("/tender-offer-programs", params={
        "company": "Acme Inc",
        "jurisdiction": "United States",
        "price_per_share": 12.50,
        "opens_at": opens,
        "closes_at": closes,
        "is_recurring": True,
    }, headers=auth_headers(admin))

    assert resp.status_code == 400
    assert "recurrence_interval_days" in resp.json()["detail"]


def test_non_recurring_program_ignores_interval(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    opens = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    closes = (datetime.utcnow() + timedelta(hours=48)).isoformat()

    resp = client.post("/tender-offer-programs", params={
        "company": "Acme Inc",
        "jurisdiction": "United States",
        "price_per_share": 12.50,
        "opens_at": opens,
        "closes_at": closes,
        "is_recurring": False,
        "recurrence_interval_days": 182,
    }, headers=auth_headers(admin))

    assert resp.status_code == 200
    assert resp.json()["recurrence_interval_days"] is None


# ---------------------------------------------------------------------------
# POST /tender-offer-programs/{id}/next-cycle
# ---------------------------------------------------------------------------

def test_admin_can_start_next_cycle_with_default_dates(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    program = make_program(
        db_session, status="closed", opens_delta_hours=-200, closes_delta_hours=-1,
        is_recurring=True, recurrence_interval_days=182,
    )

    resp = client.post(
        f"/tender-offer-programs/{program.id}/next-cycle",
        params={"price_per_share": 15.0},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    data = resp.json()
    assert float(data["price_per_share"]) == 15.0
    assert data["previous_program_id"] == program.id
    assert data["status"] == "open"
    assert data["is_recurring"] is True
    assert data["company"] == program.company
    assert data["jurisdiction"] == program.jurisdiction

    expected_opens = datetime.fromisoformat(data["opens_at"].replace("Z", ""))
    expected_closes = datetime.fromisoformat(data["closes_at"].replace("Z", ""))
    assert (expected_closes - expected_opens).days == 182


def test_next_cycle_requires_admin(client, db_session):
    holder = make_user(db_session, suffix="h1")
    program = make_program(
        db_session, status="closed", is_recurring=True, recurrence_interval_days=182,
    )

    resp = client.post(
        f"/tender-offer-programs/{program.id}/next-cycle",
        params={"price_per_share": 15.0},
        headers=auth_headers(holder),
    )

    assert resp.status_code == 403


def test_next_cycle_requires_recurring_program(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    program = make_program(db_session, status="closed", is_recurring=False)

    resp = client.post(
        f"/tender-offer-programs/{program.id}/next-cycle",
        params={"price_per_share": 15.0},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 400
    assert "recurring" in resp.json()["detail"]


def test_next_cycle_requires_closed_program(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    program = make_program(
        db_session, status="open", is_recurring=True, recurrence_interval_days=182,
    )

    resp = client.post(
        f"/tender-offer-programs/{program.id}/next-cycle",
        params={"price_per_share": 15.0},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 400
    assert "closed" in resp.json()["detail"]


def test_next_cycle_rejects_non_positive_price(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    program = make_program(
        db_session, status="closed", is_recurring=True, recurrence_interval_days=182,
    )

    resp = client.post(
        f"/tender-offer-programs/{program.id}/next-cycle",
        params={"price_per_share": 0},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 400


def test_next_cycle_with_explicit_dates_overrides_interval(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    program = make_program(
        db_session, status="closed", is_recurring=True, recurrence_interval_days=182,
    )
    explicit_opens = (datetime.utcnow() + timedelta(days=30)).isoformat()
    explicit_closes = (datetime.utcnow() + timedelta(days=45)).isoformat()

    resp = client.post(
        f"/tender-offer-programs/{program.id}/next-cycle",
        params={
            "price_per_share": 15.0,
            "opens_at": explicit_opens,
            "closes_at": explicit_closes,
        },
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["opens_at"].startswith(explicit_opens[:16])


def test_next_cycle_404_for_missing_program(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")

    resp = client.post(
        "/tender-offer-programs/999999/next-cycle",
        params={"price_per_share": 15.0},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 404


def test_next_cycle_rejects_canada(client, db_session):
    admin = make_user(db_session, suffix="a1", account_type="admin")
    # A program somehow marked Canada (shouldn't exist via normal create,
    # but the next-cycle endpoint re-checks independently as a safety net).
    program = make_program(
        db_session, jurisdiction="Canada", status="closed",
        is_recurring=True, recurrence_interval_days=182,
    )

    resp = client.post(
        f"/tender-offer-programs/{program.id}/next-cycle",
        params={"price_per_share": 15.0},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 400
    assert "Canada" in resp.json()["detail"]
