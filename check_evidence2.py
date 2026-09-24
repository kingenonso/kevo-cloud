import requests

BASE = "http://127.0.0.1:8000"

r = requests.post(f"{BASE}/login", json={"email": "authtest@kevo.local", "password": "AdminTest2026x"})
admin_token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {admin_token}"}

r = requests.get(f"{BASE}/evidence/2", headers=headers)
print("evidence 2 current state:", r.status_code, r.text)
