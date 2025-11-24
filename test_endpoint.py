#!/usr/bin/env python3
"""
Quick test script for PodPing webhook endpoint
Tests compatibility with Podscan.fm format
"""

import sys
import json
import requests
from datetime import datetime

def test_endpoint(url):
    """Test the webhook endpoint with sample data"""
    
    print(f"🔍 Testing endpoint: {url}")
    print("-" * 50)
    
    # Test payload matching PHP format
    test_data = {
        "urls": [
            "https://example1.com/podcast.rss",
            "https://example2.com/feed.xml",
            "https://example3.com/rss"
        ]
    }
    
    try:
        # Send test request
        response = requests.post(
            url,
            json=test_data,
            timeout=10,
            headers={'Content-Type': 'application/json'}
        )
        
        print(f"✓ Status Code: {response.status_code}")
        print(f"✓ Response: {response.text[:200]}")
        
        if response.status_code == 200:
            print("\n✅ SUCCESS - Endpoint is working!")
            return True
        else:
            print(f"\n⚠️  WARNING - Unexpected status code: {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR - Could not connect to endpoint")
        print("   Check that the URL is correct and server is running")
        return False
    except requests.exceptions.Timeout:
        print("\n❌ ERROR - Request timed out")
        return False
    except Exception as e:
        print(f"\n❌ ERROR - {str(e)}")
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = "http://localhost:8080/-/podping"
    
    success = test_endpoint(url)
    sys.exit(0 if success else 1)
