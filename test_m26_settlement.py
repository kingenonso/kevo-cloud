"""
Tests for M26's first slice (2026-09-19): Settlement status tracking,
orchestration-only.

KEVO never holds client funds or acts as custodian. POST /settlement-records
begins tracking (admin-only, requires the transaction be "accepted", flips
the transaction to "settlement_pending"). Two admin-only confirmation
endpoints record what a real escrow provider would eventually report:
funds received and shares confirmed transferable. Funds can only be
released once both are true (sequential, not atomic -- M26E's scope).
Releasing funds also completes the underlying transaction.
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

from models import (
    Base, User as UserModel, Listing as ListingModel, Transaction,
    SettlementRecord,
)
from app import app, get_db, hash_password, create_access_token
from unittest.mock import patch


@pytest.fixture(autouse=True)
def mock_escrow_client():
    """
    M26E - none of these tests should ever make a real network call to
    Escrow.com. Every escrow_client function is replaced with a fake that
    returns a realistic-shaped response; tests that care about the
    specifics of what was called can still inspect these mocks directly.
    """
    with patch("escrow_client.create_transaction") as mock_create, \
         patch("escrow_client.agree_as_customer") as mock_agree, \
         patch("escrow_client.mark_shipped") as mock_ship, \
         patch("escrow_client.mark_received") as mock_receive, \
         patch("escrow_client.get_transaction") as mock_get:
        mock_create.return_value = {"id": 999999}
        mock_agree.return_value = {"id": 999999}
        mock_ship.return_value = {"id": 999999}
        mock_receive.return_value = {"id": 999999}
        mock_get.return_value = {
            "items": [{"schedule": [{"status": {
                "payment_received": False, "disbursed_to_beneficiary": False
            }}]}]
        }
        yield {
            "create_transaction": mock_create,
            "agree_as_customer": mock_agree,
            "mark_shipped": mock_ship,
            "mark_received": mock_receive,
            "get_transaction": mock_get,
        }


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


def make_user(db, suffix="1", role="buyer", account_type="participant", kyc_status="not_started"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"m26user{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller, quantity=1000):
    listing = ListingModel(
        seller_id=seller.id, company="Acme Inc", asset_type="Private Shares",
        quantity=quantity, asking_price=50.0, is_transferable=True,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_transaction(db, listing, buyer, quantity=100, status="accepted", agreed_price=10.0):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=quantity, agreed_price=agreed_price, status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def make_settlement_record(db, transaction, status="pending", funds_received=False,
                            shares_confirmed_transferable=False):
    record = SettlementRecord(
        transaction_id=transaction.id, status=status,
        funds_received=funds_received,
        shares_confirmed_transferable=shares_confirmed_transferable,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


# --- POST /settlement-records ---

def test_admin_can_create_settlement_record(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    resp = client.post("/settlement-records", headers=auth_headers(admin), params={"transaction_id": txn.id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["transaction_id"] == txn.id
    assert body["funds_received"] is False
    assert body["shares_confirmed_transferable"] is False

    db_session.refresh(txn)
    assert txn.status == "settlement_pending"


def test_non_admin_cannot_create_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    resp = client.post("/settlement-records", headers=auth_headers(seller), params={"transaction_id": txn.id})
    assert resp.status_code == 403


def test_create_unauthenticated_401(client, db_session):
    resp = client.post("/settlement-records", params={"transaction_id": 1})
    assert resp.status_code == 401


def test_create_unknown_transaction_404(client, db_session):
    admin = make_user(db_session, "1", account_type="admin")
    resp = client.post("/settlement-records", headers=auth_headers(admin), params={"transaction_id": 999999})
    assert resp.status_code == 404


def test_create_wrong_status_400(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="interested")

    resp = client.post("/settlement-records", headers=auth_headers(admin), params={"transaction_id": txn.id})
    assert resp.status_code == 400


def test_create_duplicate_400(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    make_settlement_record(db_session, txn)

    resp = client.post("/settlement-records", headers=auth_headers(admin), params={"transaction_id": txn.id})
    assert resp.status_code == 400


# --- Escrow creation failure never loses the attempt / never allows a
# duplicate transaction on Escrow.com on retry ---

def test_create_when_escrow_fails_persists_unconfirmed_record_502(client, db_session, mock_escrow_client):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    mock_escrow_client["create_transaction"].side_effect = Exception("timed out waiting on Escrow.com")

    resp = client.post("/settlement-records", headers=auth_headers(admin), params={"transaction_id": txn.id})
    assert resp.status_code == 502

    record = db_session.query(SettlementRecord).filter(SettlementRecord.transaction_id == txn.id).first()
    assert record is not None
    assert record.status == "escrow_creation_unconfirmed"
    assert record.escrow_provider_reference is None

    db_session.refresh(txn)
    assert txn.status == "accepted"


def test_create_retry_after_unconfirmed_failure_gets_409_not_a_duplicate(client, db_session, mock_escrow_client):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    mock_escrow_client["create_transaction"].side_effect = Exception("timed out")
    client.post("/settlement-records", headers=auth_headers(admin), params={"transaction_id": txn.id})

    mock_escrow_client["create_transaction"].side_effect = None
    mock_escrow_client["create_transaction"].return_value = {"id": 888888}
    resp = client.post("/settlement-records", headers=auth_headers(admin), params={"transaction_id": txn.id})
    assert resp.status_code == 409
    mock_escrow_client["create_transaction"].assert_called_once()


def test_resolve_unconfirmed_with_reference_completes_settlement(client, db_session, mock_escrow_client):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    mock_escrow_client["create_transaction"].side_effect = Exception("timed out")
    client.post("/settlement-records", headers=auth_headers(admin), params={"transaction_id": txn.id})
    record = db_session.query(SettlementRecord).filter(SettlementRecord.transaction_id == txn.id).first()

    resp = client.put(
        f"/settlement-records/{record.id}/resolve-unconfirmed-creation",
        headers=auth_headers(admin),
        params={"escrow_provider_reference": "777777"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["escrow_provider_reference"] == "777777"

    db_session.refresh(txn)
    assert txn.status == "settlement_pending"


def test_resolve_unconfirmed_without_reference_marks_abandoned_and_allows_clean_retry(client, db_session, mock_escrow_client):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    mock_escrow_client["create_transaction"].side_effect = Exception("timed out")
    client.post("/settlement-records", headers=auth_headers(admin), params={"transaction_id": txn.id})
    record = db_session.query(SettlementRecord).filter(SettlementRecord.transaction_id == txn.id).first()

    resolve_resp = client.put(
        f"/settlement-records/{record.id}/resolve-unconfirmed-creation",
        headers=auth_headers(admin),
    )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["status"] == "escrow_creation_abandoned"

    mock_escrow_client["create_transaction"].side_effect = None
    mock_escrow_client["create_transaction"].return_value = {"id": 555555}
    retry_resp = client.post("/settlement-records", headers=auth_headers(admin), params={"transaction_id": txn.id})
    assert retry_resp.status_code == 200
    body = retry_resp.json()
    assert body["id"] == record.id
    assert body["status"] == "pending"
    assert body["escrow_provider_reference"] == "555555"

    assert db_session.query(SettlementRecord).filter(SettlementRecord.transaction_id == txn.id).count() == 1


def test_resolve_unconfirmed_non_admin_403(client, db_session, mock_escrow_client):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")

    mock_escrow_client["create_transaction"].side_effect = Exception("timed out")
    client.post("/settlement-records", headers=auth_headers(admin), params={"transaction_id": txn.id})
    record = db_session.query(SettlementRecord).filter(SettlementRecord.transaction_id == txn.id).first()

    resp = client.put(
        f"/settlement-records/{record.id}/resolve-unconfirmed-creation",
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 403


def test_resolve_unconfirmed_wrong_state_400(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    record = make_settlement_record(db_session, txn, status="pending")

    resp = client.put(
        f"/settlement-records/{record.id}/resolve-unconfirmed-creation",
        headers=auth_headers(admin),
        params={"escrow_provider_reference": "123"},
    )
    assert resp.status_code == 400


# --- PUT /settlement-records/{id}/confirm-funds-received ---

def test_admin_can_confirm_funds_received(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    record = make_settlement_record(db_session, txn)

    resp = client.put(
        f"/settlement-records/{record.id}/confirm-funds-received",
        headers=auth_headers(admin),
        params={"escrow_provider_reference": "ESC-TEST-001"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["funds_received"] is True
    assert body["funds_received_at"] is not None
    assert body["escrow_provider_reference"] == "ESC-TEST-001"
    assert body["status"] == "in_progress"


def test_non_admin_cannot_confirm_funds_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    record = make_settlement_record(db_session, txn)

    resp = client.put(f"/settlement-records/{record.id}/confirm-funds-received", headers=auth_headers(seller))
    assert resp.status_code == 403


def test_confirm_funds_unknown_id_404(client, db_session):
    admin = make_user(db_session, "1", account_type="admin")
    resp = client.put("/settlement-records/999999/confirm-funds-received", headers=auth_headers(admin))
    assert resp.status_code == 404


def test_confirm_funds_unauthenticated_401(client, db_session):
    resp = client.put("/settlement-records/1/confirm-funds-received")
    assert resp.status_code == 401


# --- PUT /settlement-records/{id}/confirm-shares-transferable ---

def test_admin_can_confirm_shares_transferable(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    record = make_settlement_record(db_session, txn)

    resp = client.put(f"/settlement-records/{record.id}/confirm-shares-transferable", headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["shares_confirmed_transferable"] is True
    assert body["shares_confirmed_transferable_at"] is not None
    assert body["status"] == "in_progress"


def test_non_admin_cannot_confirm_shares_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    record = make_settlement_record(db_session, txn)

    resp = client.put(f"/settlement-records/{record.id}/confirm-shares-transferable", headers=auth_headers(buyer))
    assert resp.status_code == 403


# --- PUT /settlement-records/{id}/release-funds ---

def test_release_fails_when_neither_confirmed_400(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    record = make_settlement_record(db_session, txn)

    resp = client.put(f"/settlement-records/{record.id}/release-funds", headers=auth_headers(admin))
    assert resp.status_code == 400


def test_release_fails_when_only_funds_confirmed_400(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    record = make_settlement_record(db_session, txn, funds_received=True)

    resp = client.put(f"/settlement-records/{record.id}/release-funds", headers=auth_headers(admin))
    assert resp.status_code == 400


def test_release_fails_when_only_shares_confirmed_400(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    record = make_settlement_record(db_session, txn, shares_confirmed_transferable=True)

    resp = client.put(f"/settlement-records/{record.id}/release-funds", headers=auth_headers(admin))
    assert resp.status_code == 400


def test_release_succeeds_when_both_confirmed(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    record = make_settlement_record(db_session, txn, funds_received=True, shares_confirmed_transferable=True)

    resp = client.put(f"/settlement-records/{record.id}/release-funds", headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["funds_released"] is True
    assert body["funds_released_at"] is not None
    assert body["status"] == "completed"

    db_session.refresh(txn)
    assert txn.status == "completed"


def test_non_admin_cannot_release_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    record = make_settlement_record(db_session, txn, funds_received=True, shares_confirmed_transferable=True)

    resp = client.put(f"/settlement-records/{record.id}/release-funds", headers=auth_headers(seller))
    assert resp.status_code == 403


def test_release_unknown_id_404(client, db_session):
    admin = make_user(db_session, "1", account_type="admin")
    resp = client.put("/settlement-records/999999/release-funds", headers=auth_headers(admin))
    assert resp.status_code == 404


# --- GET /settlement-records (list) ---

def test_list_scoped_to_own_transactions(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    make_settlement_record(db_session, txn)

    resp_seller = client.get("/settlement-records", headers=auth_headers(seller))
    assert resp_seller.status_code == 200
    assert len(resp_seller.json()) == 1

    resp_buyer = client.get("/settlement-records", headers=auth_headers(buyer))
    assert resp_buyer.status_code == 200
    assert len(resp_buyer.json()) == 1

    resp_stranger = client.get("/settlement-records", headers=auth_headers(stranger))
    assert resp_stranger.status_code == 200
    assert len(resp_stranger.json()) == 0


def test_admin_sees_all_in_list(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    make_settlement_record(db_session, txn)

    resp = client.get("/settlement-records", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_unauthenticated_401(client, db_session):
    resp = client.get("/settlement-records")
    assert resp.status_code == 401


# --- GET /settlement-records/{id} ---

def test_get_by_id_party_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    record = make_settlement_record(db_session, txn)

    for user in (seller, buyer):
        resp = client.get(f"/settlement-records/{record.id}", headers=auth_headers(user))
        assert resp.status_code == 200


def test_get_by_id_admin_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    record = make_settlement_record(db_session, txn)

    resp = client.get(f"/settlement-records/{record.id}", headers=auth_headers(admin))
    assert resp.status_code == 200


def test_get_by_id_non_party_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    record = make_settlement_record(db_session, txn)

    resp = client.get(f"/settlement-records/{record.id}", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_get_by_id_unknown_404(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    resp = client.get("/settlement-records/999999", headers=auth_headers(seller))
    assert resp.status_code == 404


def test_get_by_id_unauthenticated_401(client, db_session):
    resp = client.get("/settlement-records/1")
    assert resp.status_code == 401
