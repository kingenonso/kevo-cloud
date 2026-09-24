import requests

BASE = "http://127.0.0.1:8000"

r = requests.post(f"{BASE}/login", json={"email": "authtest@kevo.local", "password": "AdminTest2026x"})
admin_token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {admin_token}"}

r = requests.put(f"{BASE}/evidence/2/verify", params={"status": "verified"}, headers=headers)
print("1. verify_evidence:", r.status_code, r.text)

r = requests.get(f"{BASE}/audit-log", headers=headers)
entries = r.json()
matching = [e for e in entries if e["action"] == "evidence_verified" and e["target_id"] == 2]
print("2. matching evidence_verified audit entries:", matching)
