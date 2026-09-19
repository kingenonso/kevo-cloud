"""
Tests for M27's first slice: Hash-Chained Compliance Decision Ledger.
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
    ComplianceDecisionLedger,
)
from app import app, get_db, hash_password, create_access_token, GENESIS_HASH


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
        email=f"m27user{suffix}-{id(object())}@example.com",
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


def txn_payload(listing_id, buyer_id, quantity=100, agreed_price=10.0):
    return {
        "listing_id": listing_id, "buyer_id": buyer_id,
        "quantity": quantity, "agreed_price": agreed_price,
    }


def create_real_transaction(client, db, seller=None, buyer=None, quantity=100, agreed_price=10.0):
    if seller is None:
        seller = make_user(db, "seller", role="seller")
    if buyer is None:
        buyer = make_user(db, "buyer", role="buyer")
    listing = make_listing(db, seller)
    resp = client.post(
        "/transactions", json=txn_payload(listing.id, buyer.id, quantity, agreed_price),
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 200
    txn_id = resp.json()["transaction"]["id"]
    return seller, buyer, listing, txn_id


def test_creating_transaction_logs_ledger_entry(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    entries = db_session.query(ComplianceDecisionLedger).filter(
        ComplianceDecisionLedger.transaction_id == txn_id
    ).all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.triggered_by == "transaction_created"
    assert entry.buyer_id == buyer.id
    assert entry.listing_id == listing.id
    assert entry.decision_status in ("blocked", "review")


def test_first_entry_previous_hash_is_genesis(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    entry = db_session.query(ComplianceDecisionLedger).filter(
        ComplianceDecisionLedger.transaction_id == txn_id
    ).first()
    assert entry.previous_hash == GENESIS_HASH


def test_status_update_logs_new_ledger_entry(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    resp = client.patch(
        f"/transactions/{txn_id}/status", params={"status": "accepted"},
        headers=auth_headers(seller),
    )
    assert resp.status_code == 200
    entries = db_session.query(ComplianceDecisionLedger).filter(
        ComplianceDecisionLedger.transaction_id == txn_id
    ).order_by(ComplianceDecisionLedger.id.asc()).all()
    assert len(entries) == 2
    assert entries[1].triggered_by == "status_changed_to_accepted"


def test_second_entry_chains_to_first(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    client.patch(f"/transactions/{txn_id}/status", params={"status": "accepted"}, headers=auth_headers(seller))
    entries = db_session.query(ComplianceDecisionLedger).filter(
        ComplianceDecisionLedger.transaction_id == txn_id
    ).order_by(ComplianceDecisionLedger.id.asc()).all()
    assert entries[1].previous_hash == entries[0].entry_hash
    assert entries[1].entry_hash != entries[0].entry_hash


def test_status_update_does_not_block_on_compliance(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    resp = client.patch(
        f"/transactions/{txn_id}/status", params={"status": "accepted"},
        headers=auth_headers(seller),
    )
    assert resp.status_code == 200
    assert resp.json()["transaction"]["status"] == "accepted"


def test_buyer_can_view_own_transaction_ledger(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    resp = client.get(f"/compliance-ledger/transaction/{txn_id}", headers=auth_headers(buyer))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["hash_valid"] is True
    assert isinstance(body[0]["applicable_rule_codes"], list)


def test_seller_can_view_own_transaction_ledger(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    resp = client.get(f"/compliance-ledger/transaction/{txn_id}", headers=auth_headers(seller))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_stranger_cannot_view_transaction_ledger_403(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    stranger = make_user(db_session, "stranger")
    resp = client.get(f"/compliance-ledger/transaction/{txn_id}", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_admin_can_view_any_transaction_ledger(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    admin = make_user(db_session, "admin", account_type="admin")
    resp = client.get(f"/compliance-ledger/transaction/{txn_id}", headers=auth_headers(admin))
    assert resp.status_code == 200


def test_unauthenticated_cannot_view_transaction_ledger_401(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    resp = client.get(f"/compliance-ledger/transaction/{txn_id}")
    assert resp.status_code == 401


def test_unknown_transaction_ledger_404(client, db_session):
    admin = make_user(db_session, "admin", account_type="admin")
    resp = client.get("/compliance-ledger/transaction/999999", headers=auth_headers(admin))
    assert resp.status_code == 404


def test_party_can_view_single_ledger_entry(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    entry_id = db_session.query(ComplianceDecisionLedger).filter(
        ComplianceDecisionLedger.transaction_id == txn_id
    ).first().id
    resp = client.get(f"/compliance-ledger/{entry_id}", headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert resp.json()["hash_valid"] is True


def test_stranger_cannot_view_single_ledger_entry_403(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    stranger = make_user(db_session, "stranger")
    entry_id = db_session.query(ComplianceDecisionLedger).filter(
        ComplianceDecisionLedger.transaction_id == txn_id
    ).first().id
    resp = client.get(f"/compliance-ledger/{entry_id}", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_unknown_ledger_entry_404(client, db_session):
    admin = make_user(db_session, "admin", account_type="admin")
    resp = client.get("/compliance-ledger/999999", headers=auth_headers(admin))
    assert resp.status_code == 404


def test_unauthenticated_cannot_view_single_entry_401(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    entry_id = db_session.query(ComplianceDecisionLedger).filter(
        ComplianceDecisionLedger.transaction_id == txn_id
    ).first().id
    resp = client.get(f"/compliance-ledger/{entry_id}")
    assert resp.status_code == 401


def test_verify_requires_admin_403(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    resp = client.get("/compliance-ledger/verify", headers=auth_headers(buyer))
    assert resp.status_code == 403


def test_verify_requires_auth_401(client, db_session):
    resp = client.get("/compliance-ledger/verify")
    assert resp.status_code == 401


def test_verify_valid_on_clean_chain(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    client.patch(f"/transactions/{txn_id}/status", params={"status": "accepted"}, headers=auth_headers(seller))
    admin = make_user(db_session, "admin", account_type="admin")
    resp = client.get("/compliance-ledger/verify", headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["total_entries"] == 2
    assert body["first_invalid_entry_id"] is None


def test_verify_empty_ledger_is_valid(client, db_session):
    admin = make_user(db_session, "admin", account_type="admin")
    resp = client.get("/compliance-ledger/verify", headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["total_entries"] == 0


def test_verify_detects_tampering(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    admin = make_user(db_session, "admin", account_type="admin")
    entry = db_session.query(ComplianceDecisionLedger).filter(
        ComplianceDecisionLedger.transaction_id == txn_id
    ).first()
    entry.decision_status = "eligible_pending_review_TAMPERED"
    db_session.commit()
    resp = client.get("/compliance-ledger/verify", headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["first_invalid_entry_id"] == entry.id


def test_verify_detects_broken_chain_link(client, db_session):
    seller, buyer, listing, txn_id = create_real_transaction(client, db_session)
    client.patch(f"/transactions/{txn_id}/status", params={"status": "accepted"}, headers=auth_headers(seller))
    admin = make_user(db_session, "admin", account_type="admin")
    entries = db_session.query(ComplianceDecisionLedger).order_by(ComplianceDecisionLedger.id.asc()).all()
    second_entry = entries[1]
    second_entry.previous_hash = "f" * 64
    db_session.commit()
    resp = client.get("/compliance-ledger/verify", headers=auth_headers(admin))
    body = resp.json()
    assert body["valid"] is False
    assert body["first_invalid_entry_id"] == second_entry.id
