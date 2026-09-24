import requests, random, json
from datetime import date, timedelta, datetime
from database import SessionLocal
from models import User as UserModel

BASE = "http://127.0.0.1:8000"
suffix = random.randint(100000, 999999)

def make_user(name_suffix, role="buyer"):
    email = f"live{suffix}{name_suffix}@example.com"
    r = requests.post(f"{BASE}/users", json={
        "name": f"Live {name_suffix}", "email": email, "role": role,
        "password": "testpass123"
    })
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    r2 = requests.post(f"{BASE}/login", json={"email": email, "password": "testpass123"})
    assert r2.status_code == 200, r2.text
    token = r2.json()["access_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "email": email, **user}

def make_admin():
    from app import hash_password
    email = f"liveadmin{suffix}@example.com"
    db = SessionLocal()
    admin_row = UserModel(
        name="Live Admin", email=email, role="admin", account_type="admin",
        kyc_status="not_started", hashed_password=hash_password("testpass123"),
    )
    db.add(admin_row)
    db.commit()
    db.refresh(admin_row)
    admin_id = admin_row.id
    db.close()
    r2 = requests.post(f"{BASE}/login", json={"email": email, "password": "testpass123"})
    assert r2.status_code == 200, r2.text
    token = r2.json()["access_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "email": email, "id": admin_id}

seller = make_user("seller", role="seller")
buyer = make_user("buyer", role="buyer")
admin = make_admin()
print("Created seller id=%s buyer id=%s, admin id=%s" % (seller["id"], buyer["id"], admin["id"]))

r = requests.post(f"{BASE}/listings", headers=seller["headers"], json={
    "seller_id": seller["id"], "company": f"LiveCo{suffix}", "asset_type": "Private Shares",
    "quantity": 1000, "asking_price": 50.0, "is_transferable": True
})
assert r.status_code == 200, r.text
listing = r.json()["listing"]
print("Listing created id=%s" % listing["id"])

r = requests.post(f"{BASE}/transactions", headers=buyer["headers"], json={
    "listing_id": listing["id"], "buyer_id": buyer["id"], "quantity": 100, "agreed_price": 10000.0
})
assert r.status_code == 200, r.text
txn = r.json()["transaction"]
print("Transaction created id=%s status=%s" % (txn["id"], txn["status"]))

first_due = date.today() + timedelta(days=1)
r = requests.post(f"{BASE}/seller-financing-agreements", headers=seller["headers"], json={
    "transaction_id": txn["id"], "principal_amount": 3000.0, "annual_interest_rate_pct": 0,
    "term_months": 3, "payment_frequency": "monthly", "first_payment_due_date": str(first_due),
    "restricts_transfer_until_paid": True
})
assert r.status_code == 200, r.text
agreement = r.json()
print("SF Agreement created id=%s status=%s restricts_transfer=%s" % (agreement["id"], agreement["status"], agreement["restricts_transfer_until_paid"]))

r = requests.get(f"{BASE}/seller-financing-agreements/{agreement['id']}/payments", headers=buyer["headers"])
payments = r.json()
print("Payments:", [(p["installment_number"], p["due_date"], p["amount_due"], p["status"]) for p in payments])
assert len(payments) == 3

r = requests.post(f"{BASE}/seller-financing-agreements/{agreement['id']}/reserve", headers=seller["headers"], json={
    "required_amount": 500.0, "notes": "one installment held as reserve"
})
assert r.status_code == 200, r.text
reserve = r.json()
print("Reserve created status=%s" % reserve["status"])

r = requests.put(f"{BASE}/seller-financing-agreements/{agreement['id']}/reserve/fund", headers=admin["headers"], params={
    "funded_reference": "escrow.com sandbox txn #LIVE-1"
})
assert r.status_code == 200, r.text
print("Reserve funded status=%s" % r.json()["status"])

r = requests.post(f"{BASE}/seller-financing-agreements/{agreement['id']}/collateral", headers=buyer["headers"], json={
    "description": "20 shares of a different company held as collateral", "collateral_type": "other_securities",
    "estimated_value": 2000.0
})
assert r.status_code == 200, r.text
collateral = r.json()
print("Collateral created id=%s legal_review_status=%s" % (collateral["id"], collateral["legal_review_status"]))

r = requests.put(f"{BASE}/seller-financing-agreements/{agreement['id']}/collateral/{collateral['id']}", headers=admin["headers"], params={
    "legal_review_status": "reviewed_flagged",
    "legal_review_notes": "Pledge of shares in a private company needs a control agreement or UCC-1 to actually perfect - flagged for counsel, not enforceable as-is."
})
assert r.status_code == 200, r.text
print("Collateral legal review updated -> %s" % r.json()["legal_review_status"])

r = requests.post(f"{BASE}/listings", headers=buyer["headers"], json={
    "seller_id": buyer["id"], "company": f"LiveCo{suffix}", "asset_type": "Private Shares",
    "quantity": 10, "asking_price": 55.0
})
print("Buyer tries to relist financed position -> status=%s detail=%s" % (r.status_code, r.json().get("detail")))
assert r.status_code == 403

payment1_id = payments[0]["id"]
r = requests.put(f"{BASE}/seller-financing-agreements/{agreement['id']}/payments/{payment1_id}/confirm", headers=seller["headers"])
assert r.status_code == 200, r.text
print("Payment 1 confirmed status=%s" % r.json()["status"])

r = requests.get(f"{BASE}/seller-financing-agreements/{agreement['id']}/summary", headers=buyer["headers"])
summary = r.json()
print("Summary:", json.dumps(summary, indent=2))
assert summary["payments_paid"] == 1
assert summary["reserve"]["status"] == "funded"
assert len(summary["collateral"]) == 1

db = SessionLocal()
from models import SellerFinancingPayment
p2 = db.query(SellerFinancingPayment).filter(SellerFinancingPayment.id == payments[1]["id"]).first()
p2.due_date = date.today() - timedelta(days=2)
db.commit()
db.close()

r = requests.post(f"{BASE}/seller-financing-agreements/reminders/run", headers=admin["headers"])
assert r.status_code == 200, r.text
print("Reminder scan result:", r.json())
assert r.json()["failed"] >= 1

db = SessionLocal()
p2_after = db.query(SellerFinancingPayment).filter(SellerFinancingPayment.id == payments[1]["id"]).first()
print("Payment 2 after reminder scan: status=%s" % p2_after.status)
db.close()

r = requests.put(f"{BASE}/seller-financing-agreements/{agreement['id']}/default", headers=seller["headers"], params={
    "default_reason": "Buyer stopped paying after installment 1"
})
assert r.status_code == 200, r.text
print("Agreement marked defaulted status=%s" % r.json()["status"])

r = requests.post(f"{BASE}/buyer-interests", headers=buyer["headers"], json={
    "buyer_id": buyer["id"], "company": "Some Other Co", "asset_type": "Private Shares",
    "desired_quantity": 10, "maximum_price": 100.0
})
print("Blocked buyer tries new interest -> status=%s detail=%s" % (r.status_code, r.json().get("detail")))
assert r.status_code == 403

r = requests.put(f"{BASE}/seller-financing-agreements/{agreement['id']}/resolve-default", headers=admin["headers"], params={
    "resolution_notes": "Parties settled outside the platform; buyer cleared to resume"
})
assert r.status_code == 200, r.text
print("Default resolved status=%s" % r.json()["status"])

r = requests.post(f"{BASE}/buyer-interests", headers=buyer["headers"], json={
    "buyer_id": buyer["id"], "company": "Some Other Co", "asset_type": "Private Shares",
    "desired_quantity": 10, "maximum_price": 100.0
})
print("Unblocked buyer retries new interest -> status=%s" % r.status_code)
assert r.status_code == 200

db = SessionLocal()
from models import SellerFinancingAgreement, SellerFinancingReserve, SellerFinancingCollateral
buyer_row = db.query(UserModel).filter(UserModel.id == buyer["id"]).first()
agreement_row = db.query(SellerFinancingAgreement).filter(SellerFinancingAgreement.id == agreement["id"]).first()
reserve_row = db.query(SellerFinancingReserve).filter(SellerFinancingReserve.agreement_id == agreement["id"]).first()
collateral_row = db.query(SellerFinancingCollateral).filter(SellerFinancingCollateral.agreement_id == agreement["id"]).first()
print("DB cross-check: buyer.seller_financing_blocked=%s, agreement.status=%s, reserve.status=%s, collateral.legal_review_status=%s" % (
    buyer_row.seller_financing_blocked, agreement_row.status, reserve_row.status, collateral_row.legal_review_status
))
assert buyer_row.seller_financing_blocked is False
assert agreement_row.status == "resolved"
assert reserve_row.status == "funded"
assert collateral_row.legal_review_status == "reviewed_flagged"
db.close()

print("\nALL LIVE CHECKS PASSED")
