"""
Live verification of M31's Compliant-Communication Gating
(POST/GET /transactions/{transaction_id}/messages) against the real
running server and database.
"""
import requests
from database import SessionLocal
from models import User as UserModel

BASE = "http://127.0.0.1:8000"


def signup_and_login(suffix, role="buyer"):
    email = f"livemsg{suffix}@example.com"
    password = "testpass123"
    requests.post(f"{BASE}/users", json={
        "name": f"Live User {suffix}",
        "email": email,
        "password": password,
        "role": role,
        "jurisdiction": "United States",
        "phone_number": "+15550000000",
        "date_of_birth": "1990-01-01",
        "terms_accepted": True,
    })
    resp = requests.post(f"{BASE}/login", json={"email": email, "password": password})
    resp.raise_for_status()
    return email, resp.json()["access_token"]


seller_email, seller_token = signup_and_login("seller", role="seller")
buyer_email, buyer_token = signup_and_login("buyer", role="buyer")
stranger_email, stranger_token = signup_and_login("stranger", role="buyer")

db = SessionLocal()
seller = db.query(UserModel).filter(UserModel.email == seller_email).first()
buyer = db.query(UserModel).filter(UserModel.email == buyer_email).first()
stranger = db.query(UserModel).filter(UserModel.email == stranger_email).first()

admin_email = "livemsg-admin@example.com"
admin = db.query(UserModel).filter(UserModel.email == admin_email).first()
if admin is None:
    from app import hash_password
    admin = UserModel(
        name="Live Admin", email=admin_email, role="buyer",
        account_type="admin", hashed_password=hash_password("testpass123"),
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
admin_login = requests.post(f"{BASE}/login", json={"email": admin_email, "password": "testpass123"})
admin_login.raise_for_status()
admin_token = admin_login.json()["access_token"]

print(f"seller id={seller.id} buyer id={buyer.id} stranger id={stranger.id} admin id={admin.id}")

listing_resp = requests.post(
    f"{BASE}/listings",
    json={
        "seller_id": seller.id,
        "company": "Live Msg Co", "asset_type": "Private Shares",
        "quantity": 100, "asking_price": 10000,
        "issuer_jurisdiction": "United States",
    },
    headers={"Authorization": f"Bearer {seller_token}"},
)
listing_resp.raise_for_status()
listing_id = listing_resp.json()["listing"]["id"]
print(f"listing id={listing_id}")

txn_resp = requests.post(
    f"{BASE}/transactions",
    json={"listing_id": listing_id, "buyer_id": buyer.id, "quantity": 10, "agreed_price": 100},
    headers={"Authorization": f"Bearer {buyer_token}"},
)
print("transaction status:", txn_resp.status_code)
print("transaction body:", txn_resp.text)
txn_resp.raise_for_status()
txn_id = txn_resp.json()["id"] if "id" in txn_resp.json() else txn_resp.json()["transaction"]["id"]
print(f"transaction id={txn_id}")

# Buyer's KYC starts unverified -> sending should be gated
r_blocked = requests.post(
    f"{BASE}/transactions/{txn_id}/messages",
    json={"body": "hello"},
    headers={"Authorization": f"Bearer {buyer_token}"},
)
print("send while unverified status:", r_blocked.status_code, r_blocked.text)
assert r_blocked.status_code == 403, f"expected 403, got {r_blocked.status_code}"
print("Send correctly gated while buyer KYC unverified")

# Admin verifies buyer's KYC
kyc_resp = requests.put(
    f"{BASE}/users/{buyer.id}/kyc-status",
    params={"status": "verified"},
    headers={"Authorization": f"Bearer {admin_token}"},
)
kyc_resp.raise_for_status()
print("Buyer KYC verified")

# Buyer also needs a verified accredited-investor eligibility record
# (US-ACCRED-001 is a real active rule and legitimately requires it)
elig_resp = requests.post(
    f"{BASE}/investor-eligibility",
    json={
        "buyer_id": buyer.id,
        "investor_type": "individual",
        "classification": "accredited",
    },
    headers={"Authorization": f"Bearer {buyer_token}"},
)
elig_resp.raise_for_status()
elig_id = elig_resp.json()["id"] if "id" in elig_resp.json() else elig_resp.json()["investor_eligibility"]["id"]

verify_resp = requests.put(
    f"{BASE}/investor-eligibility/{elig_id}/verify",
    params={"status": "verified"},
    headers={"Authorization": f"Bearer {admin_token}"},
)
verify_resp.raise_for_status()
print("Buyer investor eligibility (accredited) verified")

# Now sending should succeed
r_send = requests.post(
    f"{BASE}/transactions/{txn_id}/messages",
    json={"body": "hello, now eligible"},
    headers={"Authorization": f"Bearer {buyer_token}"},
)
assert r_send.status_code == 200, f"expected 200, got {r_send.status_code}: {r_send.text}"
print("Send succeeded after KYC verified: 200 OK")

# Stranger cannot read
r_stranger_read = requests.get(
    f"{BASE}/transactions/{txn_id}/messages",
    headers={"Authorization": f"Bearer {stranger_token}"},
)
assert r_stranger_read.status_code == 403, f"expected 403, got {r_stranger_read.status_code}"
print("Stranger read correctly blocked: 403")

# Admin can read
r_admin_read = requests.get(
    f"{BASE}/transactions/{txn_id}/messages",
    headers={"Authorization": f"Bearer {admin_token}"},
)
assert r_admin_read.status_code == 200, f"expected 200, got {r_admin_read.status_code}"
assert len(r_admin_read.json()) == 1
print("Admin read: 200 OK, sees the one real message")

db.close()
print()
print("ALL LIVE CHECKS PASSED")
