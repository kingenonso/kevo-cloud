import requests
import time
import secrets
import hashlib
from datetime import datetime, timedelta

from database import SessionLocal
from models import PasswordResetToken

BASE = "http://127.0.0.1:8000"

ts = int(time.time())
email = f"audit-reset-{ts}@kevo.local"
password1 = "InitialPass2026x"
password2 = "ResetPass2026x"

r = requests.post(f"{BASE}/users", json={
    "name": "Audit Reset User",
    "email": email,
    "password": password1,
    "role": "buyer"
})
print("1. create_user:", r.status_code, r.json())
user_id = r.json()["user"]["id"]

r = requests.post(f"{BASE}/login", json={"email": email, "password": password1})
print("2. login (initial):", r.status_code)
token1 = r.json()["access_token"]
headers1 = {"Authorization": f"Bearer {token1}"}

print("   sleeping 3s before reset...")
time.sleep(3)

raw_token = secrets.token_urlsafe(32)
token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
now = datetime.utcnow()

db = SessionLocal()
reset_token = PasswordResetToken(
    user_id=user_id,
    token_hash=token_hash,
    created_at=now,
    expires_at=now + timedelta(minutes=30),
    used_at=None
)
db.add(reset_token)
db.commit()
db.close()
print("3. inserted reset token directly into DB")

r = requests.post(f"{BASE}/reset-password", json={"token": raw_token, "new_password": password2})
print("4. reset_password:", r.status_code, r.json())

print("   sleeping 2s before reusing old token...")
time.sleep(2)

r = requests.put(f"{BASE}/change-password", json={
    "current_password": password2,
    "new_password": password2
}, headers=headers1)
print("5. old pre-reset token after reset + gap (expect 401 revoked):", r.status_code, r.json())

r = requests.post(f"{BASE}/login", json={"email": email, "password": password2})
print("6. login (post-reset password):", r.status_code)

r = requests.post(f"{BASE}/login", json={"email": "authtest@kevo.local", "password": "AdminTest2026x"})
admin_token = r.json()["access_token"]
r = requests.get(f"{BASE}/audit-log", headers={"Authorization": f"Bearer {admin_token}"})
entries = r.json()
matching = [e for e in entries if e["action"] == "password_reset_completed" and e["target_id"] == user_id]
print("7. matching password_reset_completed audit entries:", matching)
