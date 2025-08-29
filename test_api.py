#!/usr/bin/env python3
# API Testing Script for Downloader NinjaX

import requests
import json
import time
import sys

# Configuration
BASE_URL = "http://localhost:5000"
TEST_URLS = {
    "youtube": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "instagram": "https://www.instagram.com/p/EXAMPLE/",
    "facebook": "https://www.facebook.com/video/example"
}

def test_health_check():
    """Test health check endpoint"""
    print("ðŸ” Testing health check...")
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"âœ… Health check passed: {data['status']}")
            return True
        else:
            print(f"âŒ Health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"âŒ Health check error: {e}")
        return False

def test_youtube_info():
    """Test YouTube info endpoint"""
    print("ðŸŽ¥ Testing YouTube info...")
    try:
        payload = {"url": TEST_URLS["youtube"]}
        response = requests.post(
            f"{BASE_URL}/api/youtube/info",
            json=payload,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print(f"âœ… YouTube info: {data.get('title', 'Unknown')[:50]}...")
                return True
            else:
                print(f"âŒ YouTube info failed: {data.get('error')}")
                return False
        else:
            print(f"âŒ YouTube info HTTP error: {response.status_code}")
            return False
    except Exception as e:
        print(f"âŒ YouTube info error: {e}")
        return False

def test_rate_limiting():
    """Test rate limiting"""
    print("ðŸš¦ Testing rate limiting...")
    try:
        payload = {"url": TEST_URLS["youtube"]}

        # Make multiple rapid requests
        for i in range(15):
            response = requests.post(
                f"{BASE_URL}/api/youtube/info",
                json=payload,
                timeout=5
            )
            if response.status_code == 429:
                print("âœ… Rate limiting is working")
                return True
            time.sleep(0.1)

        print("âš ï¸ Rate limiting may not be configured")
        return False
    except Exception as e:
        print(f"âŒ Rate limiting test error: {e}")
        return False

def test_security():
    """Test security features"""
    print("ðŸ›¡ï¸ Testing security...")

    # Test invalid URL
    try:
        payload = {"url": "not-a-url"}
        response = requests.post(
            f"{BASE_URL}/api/youtube/info",
            json=payload,
            timeout=5
        )

        if response.status_code == 400:
            print("âœ… URL validation is working")
        else:
            print("âš ï¸ URL validation may be weak")
    except Exception as e:
        print(f"âŒ Security test error: {e}")

def run_all_tests():
    """Run all tests"""
    print("ðŸš€ Starting API tests for Downloader NinjaX\n")

    tests = [
        ("Health Check", test_health_check),
        ("YouTube Info", test_youtube_info),
        ("Rate Limiting", test_rate_limiting),
        ("Security", test_security),
    ]

    results = []
    for test_name, test_func in tests:
        print(f"\n{'='*50}")
        result = test_func()
        results.append((test_name, result))

    print(f"\n{'='*50}")
    print("ðŸ“Š Test Results Summary:")
    print("="*50)

    passed = 0
    for test_name, result in results:
        status = "âœ… PASSED" if result else "âŒ FAILED"
        print(f"{test_name:<20}: {status}")
        if result:
            passed += 1

    print(f"\nOverall: {passed}/{len(tests)} tests passed")

    if passed == len(tests):
        print("ðŸŽ‰ All tests passed! API is working correctly.")
        return True
    else:
        print("âš ï¸ Some tests failed. Check the logs above.")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
