"""
Live verification of the 2026-09-25 authorization fix on
GET /compliance-rules/matches/{buyer_id}/{listing_id} against the real
running server and real database.
"""
import requests
from database import SessionLocal
from models import User as UserModel

BASE = "http://127.0.0.1:8000"


def signup_and_login(suffix, role="buyer"):
    email = f"livecompmatch{suffix}@example.com"
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
    token = resp.json()["access_token"]
    return email, token


seller_email, seller_token = signup_and_login("seller", role="seller")
buyer_email, buyer_token = signup_and_login("buyer", role="buyer")
stranger_email, stranger_token = signup_and_login("stranger", role="buyer")

db = SessionLocal()
seller = db.query(UserModel).filter(UserModel.email == seller_email).first()
buyer = db.query(UserModel).filter(UserModel.email == buyer_email).first()
stranger = db.query(UserModel).filter(UserModel.email == stranger_email).first()

admin_email = "livecompmatch-admin@example.com"
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
        "company": "Live Co", "asset_type": "Private Shares",
        "quantity": 100, "asking_price": 10000,
        "issuer_jurisdiction": "United States",
    },
    headers={"Authorization": f"Bearer {seller_token}"},
)
print("listing status:", listing_resp.status_code)
print("listing body:", listing_resp.text)
listing_resp.raise_for_status()
listing_id = listing_resp.json()["listing"]["id"]
print(f"listing id={listing_id}")

# Owner viewing their own matches: expect 200
r_owner = requests.get(
    f"{BASE}/compliance-rules/matches/{buyer.id}/{listing_id}",
    headers={"Authorization": f"Bearer {buyer_token}"},
)
assert r_owner.status_code == 200, f"expected 200, got {r_owner.status_code}: {r_owner.text}"
print("Owner viewing own matches: 200 OK")

# Admin viewing another buyer's matches: expect 200
r_admin = requests.get(
    f"{BASE}/compliance-rules/matches/{buyer.id}/{listing_id}",
    headers={"Authorization": f"Bearer {admin_token}"},
)
assert r_admin.status_code == 200, f"expected 200, got {r_admin.status_code}: {r_admin.text}"
print("Admin viewing buyer's matches: 200 OK")

# Stranger viewing another buyer's matches: expect 403 (the fix)
r_stranger = requests.get(
    f"{BASE}/compliance-rules/matches/{buyer.id}/{listing_id}",
    headers={"Authorization": f"Bearer {stranger_token}"},
)
assert r_stranger.status_code == 403, f"expected 403, got {r_stranger.status_code}: {r_stranger.text}"
print("Stranger viewing another buyer's matches: 403 correctly blocked")

db.close()
print()
print("ALL LIVE CHECKS PASSED")
