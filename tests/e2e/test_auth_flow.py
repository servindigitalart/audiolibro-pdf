import requests
import random
import sys

BASE_URL = "https://audiolibro-pdf-production.up.railway.app"

email = f"test{random.randint(1000,9999)}@example.com"
password = "TestPassword123!"

print("\n🚀 REGISTER")

register_response = requests.post(
    f"{BASE_URL}/api/v1/auth/register",
    json={
        "email": email,
        "password": password
    }
)

print("Status:", register_response.status_code)

try:
    data = register_response.json()
    print("Response:", data)
except Exception:
    print(register_response.text)
    sys.exit(1)

if register_response.status_code != 200:
    print("\n❌ Registration failed")
    sys.exit(1)

if "access_token" not in data:
    print("\n❌ access_token missing")
    sys.exit(1)

token = data["access_token"]

headers = {
    "Authorization": f"Bearer {token}"
}

print("\n🚀 GET ME")

me_response = requests.get(
    f"{BASE_URL}/api/v1/auth/me",
    headers=headers
)

print("Status:", me_response.status_code)

try:
    print("Response:", me_response.json())
except Exception:
    print(me_response.text)
