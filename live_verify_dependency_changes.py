import requests, random
from datetime import date, datetime
from database import SessionLocal
from models import User as UserModel, OwnershipRecord

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
stranger = make_user("stranger", role="buyer")
print("Created seller id=%s buyer id=%s stranger id=%s" % (seller["id"], buyer["id"], stranger["id"]))

r = requests.post(f"{BASE}/listings", headers=seller["headers"], json={
    "seller_id": seller["id"], "company": f"DepGraphCo{suffix}", "asset_type": "Private Shares",
    "quantity": 1000, "asking_price": 50.0, "is_transferable": True,
})
assert r.status_code == 200, r.text
listing = r.json()["listing"]
print("Listing id=%s" % listing["id"])

r = requests.post(f"{BASE}/transactions", headers=buyer["headers"], json={
    "listing_id": listing["id"], "buyer_id": buyer["id"], "quantity": 100, "agreed_price": 10000.0
})
assert r.status_code == 200, r.text
txn = r.json()["transaction"]
print("Transaction id=%s" % txn["id"])

r = requests.get(f"{BASE}/transactions/999999999/dependency-changes", headers=buyer["headers"])
assert r.status_code == 404, r.text
print("404 for unknown transaction OK")

r = requests.get(f"{BASE}/transactions/{txn['id']}/dependency-changes", headers=stranger["headers"])
assert r.status_code == 403, r.text
print("Stranger correctly blocked (403)")

baseline = requests.get(f"{BASE}/transactions/{txn['id']}/dependency-changes", headers=buyer["headers"])
assert baseline.status_code == 200, baseline.text
baseline_body = baseline.json()
print("Baseline:", baseline_body)
assert baseline_body["previous_run_id"] is None
assert baseline_body["changed_steps"] == []

repeat = requests.get(f"{BASE}/transactions/{txn['id']}/dependency-changes", headers=buyer["headers"])
assert repeat.status_code == 200, repeat.text
repeat_body = repeat.json()
assert repeat_body["previous_run_id"] == baseline_body["new_run_id"]
assert repeat_body["changed_steps"] == []
print("No changes across two identical calls OK")

db = SessionLocal()
ownership = OwnershipRecord(
    seller_id=seller["id"], listing_id=listing["id"], company=f"DepGraphCo{suffix}",
    asset_type="Private Shares", quantity=1000, verification_status="verified",
)
db.add(ownership)
db.commit()
db.close()
print("Ownership record verified directly (curated verification data, no write API)")

after = requests.get(f"{BASE}/transactions/{txn['id']}/dependency-changes", headers=buyer["headers"])
assert after.status_code == 200, after.text
after_body = after.json()
print("After ownership verified:", after_body)
assert after_body["previous_run_id"] == repeat_body["new_run_id"]

changed = {c["step_type"]: c for c in after_body["changed_steps"]}
assert "OWNERSHIP_VERIFICATION" in changed
ownership_change = changed["OWNERSHIP_VERIFICATION"]
assert ownership_change["previous"]["complete"] is False
assert ownership_change["current"]["complete"] is True
downstream_types = {d["step_type"] for d in ownership_change["downstream_steps_affected"]}
assert "CASH_RELEASE" in downstream_types
print("Ownership verification change detected, downstream steps affected:", sorted(downstream_types))

print("\nALL LIVE CHECKS PASSED")
