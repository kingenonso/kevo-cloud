import requests, random
from datetime import date, timedelta
from database import SessionLocal
from models import User as UserModel, TransferabilityRule

BASE = "http://127.0.0.1:8000"
suffix = random.randint(100000, 999999)

def make_user(name_suffix, role="buyer"):
    email = f"live{suffix}{name_suffix}@example.com"
    r = requests.post(f"{BASE}/users", json={
        "name": f"Live {name_suffix}", "email": email, "role": role,
        "password": "testpass123",
        "phone_number": "+2348000000000",
        "date_of_birth": "1990-01-01",
        "jurisdiction": "NG",
        "terms_accepted": True,
    })
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    r2 = requests.post(f"{BASE}/login", json={"email": email, "password": "testpass123"})
    assert r2.status_code == 200, r2.text
    token = r2.json()["access_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "email": email, **user}

seller = make_user("seller", role="seller")
buyer = make_user("buyer", role="buyer")
print("Created seller id=%s buyer id=%s" % (seller["id"], buyer["id"]))

r = requests.post(f"{BASE}/listings", headers=seller["headers"], json={
    "seller_id": seller["id"], "company": f"RofrCo{suffix}", "asset_type": "Private Shares",
    "quantity": 1000, "asking_price": 50.0, "is_transferable": True,
    "issuer_jurisdiction": "ZA",
})
assert r.status_code == 200, r.text
listing = r.json()["listing"]
print("Listing id=%s issuer_jurisdiction=%s" % (listing["id"], listing.get("issuer_jurisdiction")))

r = requests.post(f"{BASE}/transactions", headers=buyer["headers"], json={
    "listing_id": listing["id"], "buyer_id": buyer["id"], "quantity": 100, "agreed_price": 10000.0
})
assert r.status_code == 200, r.text
txn = r.json()["transaction"]
print("Transaction id=%s status=%s" % (txn["id"], txn["status"]))

# No API write path for TransferabilityRule -- curated data, same as the rest
# of the project's rule seeding. Created directly, matching that pattern.
db = SessionLocal()
rule_with_window = TransferabilityRule(
    jurisdiction="ZA", asset_type="Private Shares", fact_type="rofr_consent",
    rule_code=f"LIVE-ROFR-WINDOW-{suffix}",
    requirement="Company must consent under ROFR before transfer (live test, real 30-day window)",
    decision_if_unmet="block", requires_human_review=True, active=True,
    rofr_response_window_days=30,
)
rule_no_window = TransferabilityRule(
    jurisdiction="ZA", asset_type="Private Shares", fact_type="rofr_consent",
    rule_code=f"LIVE-ROFR-NOWINDOW-{suffix}",
    requirement="Company must consent under ROFR before transfer (live test, no sourced window)",
    decision_if_unmet="block", requires_human_review=True, active=True,
)
db.add(rule_with_window)
db.add(rule_no_window)
db.commit()
db.refresh(rule_with_window)
db.refresh(rule_no_window)
rule_with_window_id = rule_with_window.id
rule_no_window_id = rule_no_window.id
db.close()
print("rule_with_window id=%s rule_no_window id=%s" % (rule_with_window_id, rule_no_window_id))

r = requests.post(f"{BASE}/rofr-requests", headers=seller["headers"], json={
    "transaction_id": txn["id"], "transferability_rule_id": rule_with_window_id,
    "source_reference": "Live test: real 30-day contractual ROFR window",
})
assert r.status_code == 200, r.text
body = r.json()
print("ROFR request (with window):", body)
expected_due = (date.today() + timedelta(days=30)).isoformat()
assert body["response_due_date"] == expected_due, f"expected {expected_due}, got {body['response_due_date']}"

r2 = requests.post(f"{BASE}/rofr-requests", headers=seller["headers"], json={
    "transaction_id": txn["id"], "transferability_rule_id": rule_no_window_id,
    "source_reference": "Live test: no sourced window",
})
assert r2.status_code == 200, r2.text
body2 = r2.json()
print("ROFR request (no window):", body2)
assert body2["response_due_date"] is None

print("\nALL LIVE CHECKS PASSED")
