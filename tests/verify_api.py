import requests
import time

BASE_URL = "https://audiolibro-pdf-production.up.railway.app"

def test_endpoint(name, url):
    print(f"\n🔍 Testing {name}")
    
    try:
        start = time.time()
        response = requests.get(url, timeout=20)
        elapsed = round(time.time() - start, 2)

        print(f"Status: {response.status_code}")
        print(f"Time: {elapsed}s")

        try:
            print("Response:", response.json())
        except:
            print("Response:", response.text[:300])

        return response.status_code < 500

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


def main():
    print("=" * 50)
    print("🚀 SONORO API SMOKE TEST")
    print("=" * 50)

    tests = [
        ("Root", f"{BASE_URL}/"),
        ("Health", f"{BASE_URL}/api/v1/health"),
        ("Docs", f"{BASE_URL}/docs"),
        ("OpenAPI", f"{BASE_URL}/openapi.json"),
    ]

    passed = 0

    for name, url in tests:
        ok = test_endpoint(name, url)
        if ok:
            passed += 1

    print("\n" + "=" * 50)
    print(f"✅ Passed {passed}/{len(tests)} tests")

    if passed == len(tests):
        print("🎉 ALL TESTS PASSED")
    else:
        print("⚠️ SOME TESTS FAILED")


if __name__ == "__main__":
    main()
