#!/bin/bash

BASE="http://127.0.0.1:8000"

EMAIL="test$(date +%s)@mail.com"
PASSWORD="Test12345!"

echo "🚀 REGISTER"
REGISTER=$(curl -s -X POST "$BASE/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
echo $REGISTER

echo "\n🚀 LOGIN"
LOGIN=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
echo "LOGIN RAW: $LOGIN"

TOKEN=$(echo "LOGIN RAW: $LOGIN" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "\n🚀 ME"
curl -s "$BASE/api/v1/auth/me" \
  -H "Authorization: Bearer $TOKEN"

