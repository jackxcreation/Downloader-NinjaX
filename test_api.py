import requests
import json
import time
import threading
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('test_results.log')
    ]
)
logger = logging.getLogger(__name__)

class DownloaderNinjaXTester:
    """Comprehensive testing suite for Downloader NinjaX API"""
    
    def __init__(self, base_url="http://localhost:10000"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'DownloaderNinjaX-Tester/2.0',
            'Content-Type': 'application/json'
        })
        
        # Test results storage
        self.results = {
            'passed': 0,
            'failed': 0,
            'total': 0,
            'tests': {},
            'start_time': None,
            'end_time': None
        }
        
        # Test URLs for different platforms
        self.test_urls = {
            'youtube': [
                'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                'https://youtu.be/dQw4w9WgXcQ'
            ],
            'instagram': [
                'https://www.instagram.com/p/sample/',
                'https://www.instagram.com/reel/sample/'
            ],
            'facebook': [
                'https://www.facebook.com/watch/?v=123456789'
            ]
        }
    
    def log_test_result(self, test_name, success, message="", duration=0):
        """Log test results with detailed information"""
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{test_name}: {status} ({duration:.2f}s) - {message}")
        
        self.results['tests'][test_name] = {
            'success': success,
            'message': message,
            'duration': duration,
            'timestamp': datetime.now().isoformat()
        }
        
        if success:
            self.results['passed'] += 1
        else:
            self.results['failed'] += 1
        self.results['total'] += 1

    def test_health_endpoint(self):
        """Test basic health check endpoint"""
        test_name = "Health Check"
        start_time = time.time()
        
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=10)
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                required_fields = ['status', 'timestamp', 'version']
                
                if all(field in data for field in required_fields):
                    if data['status'] == 'healthy':
                        self.log_test_result(test_name, True, f"API healthy, version: {data.get('version')}", duration)
                        return True
                    else:
                        self.log_test_result(test_name, False, f"API status: {data['status']}", duration)
                else:
                    self.log_test_result(test_name, False, "Missing required fields in response", duration)
            else:
                self.log_test_result(test_name, False, f"HTTP {response.status_code}", duration)
                
        except requests.exceptions.Timeout:
            duration = time.time() - start_time
            self.log_test_result(test_name, False, "Request timeout", duration)
        except requests.exceptions.ConnectionError:
            duration = time.time() - start_time
            self.log_test_result(test_name, False, "Connection refused", duration)
        except Exception as e:
            duration = time.time() - start_time
            self.log_test_result(test_name, False, f"Exception: {str(e)}", duration)
        
        return False

    def test_api_status_endpoint(self):
        """Test detailed API status endpoint"""
        test_name = "API Status"
        start_time = time.time()
        
        try:
            response = self.session.get(f"{self.base_url}/api/status", timeout=10)
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                required_fields = ['service', 'version', 'endpoints', 'supported_platforms']
                
                if all(field in data for field in required_fields):
                    platforms = data.get('supported_platforms', [])
                    expected_platforms = ['youtube', 'instagram', 'facebook']
                    
                    if all(platform in platforms for platform in expected_platforms):
                        self.log_test_result(test_name, True, f"All platforms supported: {platforms}", duration)
                        return True
                    else:
                        self.log_test_result(test_name, False, f"Missing platforms: {platforms}", duration)
                else:
                    self.log_test_result(test_name, False, "Missing required fields", duration)
            else:
                self.log_test_result(test_name, False, f"HTTP {response.status_code}", duration)
                
        except Exception as e:
            duration = time.time() - start_time
            self.log_test_result(test_name, False, f"Exception: {str(e)}", duration)
        
        return False

    def test_analyze_endpoint(self, platform, url):
        """Test media analysis endpoint for specific platform"""
        test_name = f"Analyze {platform.title()}"
        start_time = time.time()
        
        try:
            payload = {
                "url": url,
                "platform": platform
            }
            
            response = self.session.post(
                f"{self.base_url}/api/analyze",
                json=payload,
                timeout=30
            )
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('success'):
                    required_fields = ['title', 'formats']
                    
                    if all(field in data for field in required_fields):
                        formats_count = len(data.get('formats', []))
                        title = data.get('title', 'Unknown')[:50]
                        
                        self.log_test_result(
                            test_name, 
                            True, 
                            f"Title: {title}..., Formats: {formats_count}", 
                            duration
                        )
                        return True
                    else:
                        self.log_test_result(test_name, False, "Missing required response fields", duration)
                else:
                    error_msg = data.get('error', 'Unknown error')
                    self.log_test_result(test_name, False, f"API Error: {error_msg}", duration)
            else:
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', 'HTTP error')
                except:
                    error_msg = f"HTTP {response.status_code}"
                
                self.log_test_result(test_name, False, error_msg, duration)
                
        except requests.exceptions.Timeout:
            duration = time.time() - start_time
            self.log_test_result(test_name, False, "Request timeout (>30s)", duration)
        except Exception as e:
            duration = time.time() - start_time
            self.log_test_result(test_name, False, f"Exception: {str(e)}", duration)
        
        return False

    def test_download_endpoint(self, platform, url, quality="HD"):
        """Test download endpoint (WARNING: Creates actual downloads)"""
        test_name = f"Download {platform.title()}"
        start_time = time.time()
        
        try:
            payload = {
                "url": url,
                "platform": platform,
                "quality": quality
            }
            
            response = self.session.post(
                f"{self.base_url}/api/download",
                json=payload,
                timeout=60  # Longer timeout for downloads
            )
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('success'):
                    filename = data.get('filename', 'unknown')
                    file_size = data.get('file_size', 0)
                    download_url = data.get('download_url', '')
                    
                    if filename and download_url:
                        self.log_test_result(
                            test_name, 
                            True, 
                            f"File: {filename}, Size: {file_size} bytes", 
                            duration
                        )
                        return True
                    else:
                        self.log_test_result(test_name, False, "Missing download info", duration)
                else:
                    error_msg = data.get('error', 'Unknown download error')
                    self.log_test_result(test_name, False, f"Download failed: {error_msg}", duration)
            else:
                self.log_test_result(test_name, False, f"HTTP {response.status_code}", duration)
                
        except requests.exceptions.Timeout:
            duration = time.time() - start_time
            self.log_test_result(test_name, False, "Download timeout (>60s)", duration)
        except Exception as e:
            duration = time.time() - start_time
            self.log_test_result(test_name, False, f"Exception: {str(e)}", duration)
        
        return False

    def test_contact_form(self):
        """Test contact form submission"""
        test_name = "Contact Form"
        start_time = time.time()
        
        try:
            payload = {
                "email": "test@downloader-ninjax.com",
                "subject": "API Test Contact",
                "message": f"Automated test message - {datetime.now().isoformat()}",
                "timestamp": datetime.now().isoformat()
            }
            
            response = self.session.post(
                f"{self.base_url}/api/submit/contact",
                json=payload,
                timeout=15
            )
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('success'):
                    email_sent = data.get('email_sent', False)
                    message = f"Form submitted, Email sent: {email_sent}"
                    self.log_test_result(test_name, True, message, duration)
                    return True
                else:
                    error_msg = data.get('error', 'Unknown contact error')
                    self.log_test_result(test_name, False, f"Form error: {error_msg}", duration)
            else:
                self.log_test_result(test_name, False, f"HTTP {response.status_code}", duration)
                
        except Exception as e:
            duration = time.time() - start_time
            self.log_test_result(test_name, False, f"Exception: {str(e)}", duration)
        
        return False

    def test_feedback_form(self):
        """Test feedback form submission"""
        test_name = "Feedback Form"
        start_time = time.time()
        
        try:
            payload = {
                "type": "suggestion",
                "message": f"Automated test feedback - {datetime.now().isoformat()}",
                "rating": 5,
                "email": "test@downloader-ninjax.com",
                "timestamp": datetime.now().isoformat()
            }
            
            response = self.session.post(
                f"{self.base_url}/api/submit/feedback",
                json=payload,
                timeout=15
            )
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('success'):
                    self.log_test_result(test_name, True, "Feedback submitted successfully", duration)
                    return True
                else:
                    error_msg = data.get('error', 'Unknown feedback error')
                    self.log_test_result(test_name, False, f"Feedback error: {error_msg}", duration)
            else:
                self.log_test_result(test_name, False, f"HTTP {response.status_code}", duration)
                
        except Exception as e:
            duration = time.time() - start_time
            self.log_test_result(test_name, False, f"Exception: {str(e)}", duration)
        
        return False

    def test_rate_limiting(self):
        """Test rate limiting functionality"""
        test_name = "Rate Limiting"
        start_time = time.time()
        
        try:
            # Make rapid requests to trigger rate limiting
            requests_made = 0
            rate_limited = False
            
            for i in range(25):  # Try 25 rapid requests
                try:
                    response = self.session.get(f"{self.base_url}/health", timeout=5)
                    requests_made += 1
                    
                    if response.status_code == 429:
                        rate_limited = True
                        break
                        
                except:
                    continue
            
            duration = time.time() - start_time
            
            if rate_limited:
                self.log_test_result(
                    test_name, 
                    True, 
                    f"Rate limiting active after {requests_made} requests", 
                    duration
                )
                return True
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"No rate limiting detected after {requests_made} requests", 
                    duration
                )
                
        except Exception as e:
            duration = time.time() - start_time
            self.log_test_result(test_name, False, f"Exception: {str(e)}", duration)
        
        return False

    def test_invalid_requests(self):
        """Test handling of invalid requests"""
        test_name = "Invalid Request Handling"
        start_time = time.time()
        
        try:
            # Test invalid analyze request
            invalid_payload = {
                "url": "not-a-valid-url",
                "platform": "invalid-platform"
            }
            
            response = self.session.post(
                f"{self.base_url}/api/analyze",
                json=invalid_payload,
                timeout=10
            )
            
            duration = time.time() - start_time
            
            if response.status_code == 400:
                data = response.json()
                if not data.get('success') and data.get('error'):
                    self.log_test_result(
                        test_name, 
                        True, 
                        f"Properly handled invalid request: {data['error'][:50]}", 
                        duration
                    )
                    return True
            
            self.log_test_result(
                test_name, 
                False, 
                f"Invalid request not properly handled: {response.status_code}", 
                duration
            )
                
        except Exception as e:
            duration = time.time() - start_time
            self.log_test_result(test_name, False, f"Exception: {str(e)}", duration)
        
        return False

    def test_cors_headers(self):
        """Test CORS headers are properly set"""
        test_name = "CORS Headers"
        start_time = time.time()
        
        try:
            response = self.session.options(f"{self.base_url}/api/analyze", timeout=10)
            duration = time.time() - start_time
            
            cors_headers = [
                'Access-Control-Allow-Origin',
                'Access-Control-Allow-Methods',
                'Access-Control-Allow-Headers'
            ]
            
            present_headers = []
            for header in cors_headers:
                if header in response.headers:
                    present_headers.append(header)
            
            if len(present_headers) >= 2:  # At least basic CORS headers
                self.log_test_result(
                    test_name, 
                    True, 
                    f"CORS headers present: {len(present_headers)}/{len(cors_headers)}", 
                    duration
                )
                return True
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Missing CORS headers: {present_headers}", 
                    duration
                )
                
        except Exception as e:
            duration = time.time() - start_time
            self.log_test_result(test_name, False, f"Exception: {str(e)}", duration)
        
        return False

    def stress_test_concurrent_requests(self, num_threads=10, requests_per_thread=5):
        """Stress test with concurrent requests"""
        test_name = f"Concurrent Stress Test ({num_threads}x{requests_per_thread})"
        start_time = time.time()
        
        def make_request(thread_id, request_id):
            try:
                response = requests.get(f"{self.base_url}/health", timeout=10)
                return {
                    'thread_id': thread_id,
                    'request_id': request_id,
                    'success': response.status_code == 200,
                    'status_code': response.status_code,
                    'response_time': time.time()
                }
            except Exception as e:
                return {
                    'thread_id': thread_id,
                    'request_id': request_id,
                    'success': False,
                    'error': str(e),
                    'response_time': time.time()
                }
        
        try:
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = []
                
                # Submit all requests
                for thread_id in range(num_threads):
                    for request_id in range(requests_per_thread):
                        future = executor.submit(make_request, thread_id, request_id)
                        futures.append(future)
                
                # Collect results
                results = []
                for future in as_completed(futures, timeout=60):
                    results.append(future.result())
            
            duration = time.time() - start_time
            
            # Analyze results
            total_requests = len(results)
            successful_requests = sum(1 for r in results if r.get('success'))
            success_rate = (successful_requests / total_requests) * 100
            
            if success_rate >= 90:  # 90% success rate threshold
                self.log_test_result(
                    test_name, 
                    True, 
                    f"Success rate: {success_rate:.1f}% ({successful_requests}/{total_requests})", 
                    duration
                )
                return True
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Low success rate: {success_rate:.1f}% ({successful_requests}/{total_requests})", 
                    duration
                )
                
        except Exception as e:
            duration = time.time() - start_time
            self.log_test_result(test_name, False, f"Exception: {str(e)}", duration)
        
        return False

    def run_comprehensive_test_suite(self, include_downloads=False, include_stress=True):
        """Run the complete test suite"""
        print("=" * 70)
        print("🥷 DOWNLOADER NINJAX - COMPREHENSIVE API TESTING SUITE")
        print("=" * 70)
        print(f"Base URL: {self.base_url}")
        print(f"Test started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("-" * 70)
        
        self.results['start_time'] = datetime.now().isoformat()
        
        # Basic connectivity tests
        logger.info("🔍 Running basic connectivity tests...")
        self.test_health_endpoint()
        self.test_api_status_endpoint()
        
        # API functionality tests
        logger.info("🧪 Running API functionality tests...")
        
        # Test analyze endpoints for each platform
        for platform, urls in self.test_urls.items():
            if urls:  # Only test if we have URLs
                self.test_analyze_endpoint(platform, urls[0])
                time.sleep(1)  # Rate limiting delay
        
        # Test download endpoints (optional)
        if include_downloads:
            logger.info("📥 Running download tests (WARNING: Creates actual files)...")
            for platform, urls in self.test_urls.items():
                if urls and platform in ['youtube']:  # Only test YouTube downloads
                    self.test_download_endpoint(platform, urls[0])
                    time.sleep(5)  # Longer delay for downloads
        
        # Test form submissions
        logger.info("📝 Running form submission tests...")
        self.test_contact_form()
        time.sleep(1)
        self.test_feedback_form()
        
        # Test security and robustness
        logger.info("🛡️ Running security and robustness tests...")
        self.test_invalid_requests()
        self.test_cors_headers()
        self.test_rate_limiting()
        
        # Stress testing (optional)
        if include_stress:
            logger.info("💪 Running stress tests...")
            self.stress_test_concurrent_requests(num_threads=5, requests_per_thread=3)
        
        self.results['end_time'] = datetime.now().isoformat()
        
        # Generate final report
        self.generate_test_report()
        
        return self.results['passed'] == self.results['total']

    def generate_test_report(self):
        """Generate comprehensive test report"""
        total_time = time.time() - time.mktime(
            datetime.fromisoformat(self.results['start_time']).timetuple()
        )
        
        print("\n" + "=" * 70)
        print("📊 TEST RESULTS SUMMARY")
        print("=" * 70)
        
        # Overall stats
        print(f"Total Tests: {self.results['total']}")
        print(f"Passed: {self.results['passed']} ✅")
        print(f"Failed: {self.results['failed']} ❌")
        print(f"Success Rate: {(self.results['passed']/self.results['total']*100):.1f}%")
        print(f"Total Duration: {total_time:.2f} seconds")
        print("-" * 70)
        
        # Individual test results
        for test_name, result in self.results['tests'].items():
            status = "✅" if result['success'] else "❌"
            duration = result['duration']
            message = result['message'][:50] + "..." if len(result['message']) > 50 else result['message']
            
            print(f"{status} {test_name:<25} ({duration:>6.2f}s) {message}")
        
        print("-" * 70)
        
        # Final status
        if self.results['failed'] == 0:
            print("🎉 ALL TESTS PASSED! API is functioning correctly.")
            print("✅ Downloader NinjaX is ready for production!")
        else:
            print("⚠️  SOME TESTS FAILED! Please review the issues above.")
            print("❌ Fix the issues before deploying to production.")
        
        print("=" * 70)
        
        # Save detailed results to file
        self.save_test_results()

    def save_test_results(self):
        """Save test results to JSON file"""
        try:
            results_file = f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            with open(results_file, 'w') as f:
                json.dump(self.results, f, indent=2)
            
            logger.info(f"Test results saved to: {results_file}")
            
        except Exception as e:
            logger.error(f"Failed to save test results: {e}")

def main():
    """Main test execution function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Downloader NinjaX API Testing Suite')
    parser.add_argument('--url', default='http://localhost:10000', 
                        help='Base URL of the API (default: http://localhost:10000)')
    parser.add_argument('--include-downloads', action='store_true',
                        help='Include download tests (creates actual files)')
    parser.add_argument('--no-stress', action='store_true',
                        help='Skip stress tests')
    parser.add_argument('--platform', choices=['youtube', 'instagram', 'facebook'],
                        help='Test specific platform only')
    parser.add_argument('--quick', action='store_true',
                        help='Run only basic tests')
    
    args = parser.parse_args()
    
    # Initialize tester
    tester = DownloaderNinjaXTester(args.url)
    
    # Configure test scope based on arguments
    if args.quick:
        # Quick test - just health and basic functionality
        logger.info("Running quick test suite...")
        tester.test_health_endpoint()
        tester.test_api_status_endpoint()
        tester.test_invalid_requests()
        
    elif args.platform:
        # Test specific platform
        logger.info(f"Testing {args.platform} platform only...")
        tester.test_health_endpoint()
        tester.test_api_status_endpoint()
        
        if args.platform in tester.test_urls and tester.test_urls[args.platform]:
            tester.test_analyze_endpoint(args.platform, tester.test_urls[args.platform][0])
            
            if args.include_downloads:
                tester.test_download_endpoint(args.platform, tester.test_urls[args.platform][0])
        
    else:
        # Full test suite
        success = tester.run_comprehensive_test_suite(
            include_downloads=args.include_downloads,
            include_stress=not args.no_stress
        )
        
        # Exit with appropriate code
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
