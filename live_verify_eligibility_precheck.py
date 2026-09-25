"""
Live verification of GET /me/eligibility-check/{listing_id} (M31
Eligibility Pre-Check) against the real running server and database.
"""
import requests
from database import SessionLocal
from models import User as UserModel

BASE = "http://127.0.0.1:8000"


def signup_and_login(suffix, role="buyer"):
    email = f"liveprecheck{suffix}@example.com"
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

db = SessionLocal()
seller = db.query(UserModel).filter(UserModel.email == seller_email).first()
buyer = db.query(UserModel).filter(UserModel.email == buyer_email).first()
print(f"seller id={seller.id} buyer id={buyer.id}")

listing_resp = requests.post(
    f"{BASE}/listings",
    json={
        "seller_id": seller.id,
        "company": "Live Precheck Co", "asset_type": "Private Shares",
        "quantity": 100, "asking_price": 10000,
        "issuer_jurisdiction": "United States",
    },
    headers={"Authorization": f"Bearer {seller_token}"},
)
listing_resp.raise_for_status()
listing_id = listing_resp.json()["listing"]["id"]
print(f"listing id={listing_id}")

# Self pre-check: expect 200, buyer_id in response is the caller's own id
r = requests.get(
    f"{BASE}/me/eligibility-check/{listing_id}",
    headers={"Authorization": f"Bearer {buyer_token}"},
)
assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
body = r.json()
assert body["buyer_id"] == buyer.id
print(f"Pre-check result: status={body['status']!r} explanation={body['explanation']!r}")
print("Buyer self-check: 200 OK, buyer_id matches caller")

# Unknown listing: expect 404
r_404 = requests.get(
    f"{BASE}/me/eligibility-check/9999999",
    headers={"Authorization": f"Bearer {buyer_token}"},
)
assert r_404.status_code == 404, f"expected 404, got {r_404.status_code}"
print("Unknown listing: 404 correctly returned")

# Unauthenticated: expect 401
r_401 = requests.get(f"{BASE}/me/eligibility-check/{listing_id}")
assert r_401.status_code == 401, f"expected 401, got {r_401.status_code}"
print("Unauthenticated: 401 correctly returned")

db.close()
print()
print("ALL LIVE CHECKS PASSED")
