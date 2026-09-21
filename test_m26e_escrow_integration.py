"""
Tests for M26E (2026-09-21): Escrow.com sandbox integration -
delivery-versus-payment orchestration on top of M26's settlement tracking.

None of these tests make a real network call to Escrow.com - every
escrow_client function is mocked. Real sandbox verification is done
separately, live, against api.escrow-sandbox.com.
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
from unittest.mock import patch

from models import (
    Base, User as UserModel, Listing as ListingModel, Transaction,
    SettlementRecord,
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


@pytest.fixture()
def mock_escrow():
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


def auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def make_user(db, suffix="1", role="buyer", account_type="participant"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"m26euser{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
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


def make_transaction(db, listing, buyer, quantity=100, status="accepted", agreed_price=250.0):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=quantity, agreed_price=agreed_price, status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def make_settlement_record(db, transaction, status="pending", funds_received=False,
                            shares_confirmed_transferable=False, funds_released=False,
                            escrow_provider_reference=None, escrow_release_initiated=False):
    record = SettlementRecord(
        transaction_id=transaction.id, status=status,
        funds_received=funds_received,
        shares_confirmed_transferable=shares_confirmed_transferable,
        funds_released=funds_released,
        escrow_provider_reference=escrow_provider_reference,
        escrow_release_initiated=escrow_release_initiated,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


# --- POST /settlement-records creates a real Escrow.com transaction ---

def test_create_calls_escrow_with_correct_details(client, db_session, mock_escrow):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, agreed_price=250.0)

    resp = client.post("/settlement-records", headers=auth_headers(admin), params={"transaction_id": txn.id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["escrow_provider_reference"] == "999999"

    mock_escrow["create_transaction"].assert_called_once_with(
        buyer_email=buyer.email,
        seller_email=seller.email,
        amount=250.0,
        currency="USD",
        description=f"KEVO transaction #{txn.id}",
    )
    assert mock_escrow["agree_as_customer"].call_count == 2
    agreed_emails = {call.args[1] for call in mock_escrow["agree_as_customer"].call_args_list}
    assert agreed_emails == {buyer.email, seller.email}


def test_create_fails_cleanly_if_escrow_create_raises(client, db_session, mock_escrow):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    mock_escrow["create_transaction"].side_effect = RuntimeError("Escrow.com API error 422: boom")

    resp = client.post("/settlement-records", headers=auth_headers(admin), params={"transaction_id": txn.id})
    assert resp.status_code == 502
    assert "Could not set up the escrow transaction" in resp.json()["detail"]
    assert db_session.query(SettlementRecord).count() == 0
    db_session.refresh(txn)
    assert txn.status == "accepted"


def test_create_fails_cleanly_if_agree_raises(client, db_session, mock_escrow):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    mock_escrow["agree_as_customer"].side_effect = RuntimeError(
        "Escrow.com API error 403: Partner account not authorized to perform actions on behalf of customers"
    )

    resp = client.post("/settlement-records", headers=auth_headers(admin), params={"transaction_id": txn.id})
    assert resp.status_code == 502
    assert db_session.query(SettlementRecord).count() == 0
    db_session.refresh(txn)
    assert txn.status == "accepted"


# --- POST /webhooks/escrow ---

def test_webhook_missing_transaction_id_400(client, db_session, mock_escrow):
    resp = client.post("/webhooks/escrow", json={"event": "payment_approved"})
    assert resp.status_code == 400


def test_webhook_unknown_transaction_is_ignored(client, db_session, mock_escrow):
    resp = client.post("/webhooks/escrow", json={"event": "payment_approved", "transaction_id": 123456})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    mock_escrow["get_transaction"].assert_not_called()


def test_webhook_flips_funds_received_from_real_transaction_state(client, db_session, mock_escrow):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    record = make_settlement_record(db_session, txn, escrow_provider_reference="555")
    mock_escrow["get_transaction"].return_value = {
        "items": [{"schedule": [{"status": {"payment_received": True, "disbursed_to_beneficiary": False}}]}]
    }

    resp = client.post("/webhooks/escrow", json={"event": "payment_approved", "transaction_id": 555})
    assert resp.status_code == 200
    db_session.refresh(record)
    assert record.funds_received is True
    assert record.funds_received_at is not None
    assert record.status == "in_progress"


def test_webhook_does_not_double_flip_already_received(client, db_session, mock_escrow):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    record = make_settlement_record(
        db_session, txn, escrow_provider_reference="555", funds_received=True, status="in_progress"
    )
    original_received_at = record.funds_received_at
    mock_escrow["get_transaction"].return_value = {
        "items": [{"schedule": [{"status": {"payment_received": True, "disbursed_to_beneficiary": False}}]}]
    }

    resp = client.post("/webhooks/escrow", json={"event": "payment_approved", "transaction_id": 555})
    assert resp.status_code == 200
    db_session.refresh(record)
    assert record.funds_received is True
    assert record.funds_received_at == original_received_at


def test_webhook_starts_release_countdown_when_shares_already_confirmed(client, db_session, mock_escrow):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    record = make_settlement_record(
        db_session, txn, escrow_provider_reference="555", shares_confirmed_transferable=True
    )
    mock_escrow["get_transaction"].return_value = {
        "items": [{"schedule": [{"status": {"payment_received": True, "disbursed_to_beneficiary": False}}]}]
    }

    resp = client.post("/webhooks/escrow", json={"event": "payment_approved", "transaction_id": 555})
    assert resp.status_code == 200
    db_session.refresh(record)
    assert record.funds_received is True
    assert record.escrow_release_initiated is True
    mock_escrow["mark_shipped"].assert_called_once_with("555", seller.email)
    mock_escrow["mark_received"].assert_called_once_with("555", buyer.email)


def test_webhook_flips_funds_released_on_disbursed(client, db_session, mock_escrow):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="settlement_pending")
    record = make_settlement_record(
        db_session, txn, escrow_provider_reference="555",
        funds_received=True, shares_confirmed_transferable=True, status="in_progress",
        escrow_release_initiated=True,
    )
    mock_escrow["get_transaction"].return_value = {
        "items": [{"schedule": [{"status": {"payment_received": True, "disbursed_to_beneficiary": True}}]}]
    }

    resp = client.post("/webhooks/escrow", json={"event": "payment_disbursed", "transaction_id": 555})
    assert resp.status_code == 200
    db_session.refresh(record)
    db_session.refresh(txn)
    assert record.funds_released is True
    assert record.funds_released_at is not None
    assert record.status == "completed"
    assert txn.status == "completed"


# --- PUT /settlement-records/{id}/confirm-shares-transferable starts the countdown ---

def test_confirm_shares_starts_countdown_when_funds_already_received(client, db_session, mock_escrow):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    record = make_settlement_record(
        db_session, txn, escrow_provider_reference="555", funds_received=True
    )

    resp = client.put(
        f"/settlement-records/{record.id}/confirm-shares-transferable",
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    db_session.refresh(record)
    assert record.escrow_release_initiated is True
    mock_escrow["mark_shipped"].assert_called_once_with("555", seller.email)
    mock_escrow["mark_received"].assert_called_once_with("555", buyer.email)


def test_confirm_shares_does_not_start_countdown_twice(client, db_session, mock_escrow):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    record = make_settlement_record(
        db_session, txn, escrow_provider_reference="555", funds_received=True,
        escrow_release_initiated=True,
    )

    resp = client.put(
        f"/settlement-records/{record.id}/confirm-shares-transferable",
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    mock_escrow["mark_shipped"].assert_not_called()
    mock_escrow["mark_received"].assert_not_called()


# --- PUT /settlement-records/{id}/release-funds reflects real Escrow.com status ---

def test_release_blocked_when_not_yet_disbursed(client, db_session, mock_escrow):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    record = make_settlement_record(
        db_session, txn, escrow_provider_reference="555",
        funds_received=True, shares_confirmed_transferable=True,
    )
    mock_escrow["get_transaction"].return_value = {
        "items": [{"schedule": [{"status": {"payment_received": True, "disbursed_to_beneficiary": False}}]}]
    }

    resp = client.put(f"/settlement-records/{record.id}/release-funds", headers=auth_headers(admin))
    assert resp.status_code == 400
    assert "not disbursed" in resp.json()["detail"]
    db_session.refresh(record)
    assert record.funds_released is False


def test_release_succeeds_once_escrow_confirms_disbursed(client, db_session, mock_escrow):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    record = make_settlement_record(
        db_session, txn, escrow_provider_reference="555",
        funds_received=True, shares_confirmed_transferable=True,
    )
    mock_escrow["get_transaction"].return_value = {
        "items": [{"schedule": [{"status": {"payment_received": True, "disbursed_to_beneficiary": True}}]}]
    }

    resp = client.put(f"/settlement-records/{record.id}/release-funds", headers=auth_headers(admin))
    assert resp.status_code == 200
    db_session.refresh(record)
    assert record.funds_released is True


def test_release_without_escrow_reference_uses_legacy_behavior(client, db_session, mock_escrow):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    record = make_settlement_record(
        db_session, txn, funds_received=True, shares_confirmed_transferable=True,
    )

    resp = client.put(f"/settlement-records/{record.id}/release-funds", headers=auth_headers(admin))
    assert resp.status_code == 200
    db_session.refresh(record)
    assert record.funds_released is True
    mock_escrow["get_transaction"].assert_not_called()
