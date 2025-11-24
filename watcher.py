#!/usr/bin/env python3
"""
PodPing Watcher for Podscan.fm - Fixed Version
Production-ready with proper error handling
"""

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Set, List, Dict, Any
from collections import deque

import beem
from beem.account import Account
from beem.blockchain import Blockchain
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# Configuration from environment
TARGET_URL = os.environ.get('TARGET_URL', 'http://localhost:8080/-/podping')
HIVE_NODES = os.environ.get('HIVE_NODES', ','.join([
    "https://api.deathwing.me",
    "https://hive-api.arcange.eu",
    "https://api.hive.blog",
    "https://api.openhive.network",
    "https://hived.emre.sh",
    "https://hive.roelandp.nl"
])).split(',')
LOOKBACK_MINUTES = int(os.environ.get('LOOKBACK_MINUTES', '5'))
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', '50'))
BATCH_TIMEOUT = int(os.environ.get('BATCH_TIMEOUT', '3'))
DEDUPE_WINDOW = int(os.environ.get('DEDUPE_WINDOW', '30'))
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

# Constants
WATCHED_OPERATION_IDS = ["podping", "pp_"]

# Logging configuration
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PodPingWatcher:
    def __init__(self):
        self.running = True
        self.http_session = self._create_http_session()
        self.url_buffer = []
        self.last_flush_time = time.time()
        self.recent_url_times = {}  # URL -> timestamp for deduplication
        self.stats = {
            'processed': 0,
            'sent': 0,
            'deduped': 0,
            'errors': 0,
            'start_time': datetime.now(timezone.utc)
        }
        self.setup_signal_handlers()
        
    def setup_signal_handlers(self):
        """Setup graceful shutdown handlers"""
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)
        
    def shutdown(self, signum, frame):
        """Graceful shutdown"""
        logger.info("Shutdown signal received, flushing remaining URLs...")
        self.running = False
        self.flush_urls()
        logger.info(f"Final stats: {self.stats}")
        sys.exit(0)
        
    def _create_http_session(self):
        """Create HTTP session with retry logic"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"]
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=20
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
        
    def get_allowed_accounts(self, acc_name="podping") -> Set[str]:
        """Get list of accounts authorized to send podpings"""
        try:
            # Try multiple nodes until one works
            for node in HIVE_NODES:
                try:
                    logger.debug(f"Trying node: {node}")
                    h = beem.Hive(node=node)
                    master_account = Account(acc_name, blockchain_instance=h)
                    following = master_account.get_following()
                    if following is not None:
                        allowed = {acc["following"] for acc in following}
                        logger.info(f"Loaded {len(allowed)} authorized accounts from {node}")
                        return allowed
                except Exception as e:
                    logger.debug(f"Failed with node {node}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error fetching allowed accounts: {e}")
            
        # Fallback to known accounts if all nodes fail
        logger.warning("Using fallback account list")
        return {
            "podping", "podping.aaa", "podping.bbb", 
            "podping.ccc", "podping.ddd", "podping.eee",
            "podping.fff", "podping.ggg", "podping.hhh",
            "podping-bbb", "podping-ccc", "podping-ddd",
            "podping-eee", "podping-fff", "podping-ggg"
        }
    
    def clean_old_urls(self):
        """Remove URLs older than DEDUPE_WINDOW from tracking"""
        current_time = time.time()
        cutoff_time = current_time - DEDUPE_WINDOW
        
        urls_to_remove = [
            url for url, timestamp in self.recent_url_times.items()
            if timestamp < cutoff_time
        ]
        
        for url in urls_to_remove:
            del self.recent_url_times[url]
            
    def should_process_url(self, url: str) -> bool:
        """Check if URL should be processed (not recently seen)"""
        current_time = time.time()
        
        # Clean old URLs periodically
        if len(self.recent_url_times) > 2000:
            self.clean_old_urls()
        
        # Check if URL was recently processed
        if url in self.recent_url_times:
            last_seen = self.recent_url_times[url]
            if current_time - last_seen < DEDUPE_WINDOW:
                self.stats['deduped'] += 1
                return False
                
        # Mark URL as processed
        self.recent_url_times[url] = current_time
        return True
        
    def process_podping(self, post_data: Dict[str, Any]):
        """Process a single podping notification"""
        try:
            json_data = json.loads(post_data.get("json", "{}"))
            
            # Extract URLs - handle both formats
            urls = json_data.get("urls", [])
            if not isinstance(urls, list):
                urls = [urls]
            
            # Also check for singular 'url' field
            if not urls and "url" in json_data:
                url = json_data.get("url")
                if url:
                    urls = [url]
            
            if not urls:
                return
                
            # Process and deduplicate URLs
            for url in urls:
                if not isinstance(url, str):
                    continue
                    
                # Basic URL validation
                if not url.startswith(('http://', 'https://')):
                    continue
                    
                # Check deduplication
                if self.should_process_url(url):
                    self.url_buffer.append(url)
                    self.stats['processed'] += 1
                    
            # Flush if buffer is full or timeout reached
            if len(self.url_buffer) >= BATCH_SIZE or \
               time.time() - self.last_flush_time > BATCH_TIMEOUT:
                self.flush_urls()
                
        except json.JSONDecodeError as e:
            logger.debug(f"Error parsing podping JSON: {e}")
        except Exception as e:
            logger.error(f"Error processing podping: {e}")
            self.stats['errors'] += 1
            
    def flush_urls(self):
        """Send accumulated URLs to PHP endpoint"""
        if not self.url_buffer:
            return
            
        # Get unique URLs from buffer
        unique_urls = list(dict.fromkeys(self.url_buffer))
        batch_size = len(unique_urls)
        
        try:
            response = self.http_session.post(
                TARGET_URL,
                json={"urls": unique_urls},
                timeout=10,
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'PodPing-Watcher/1.0'
                }
            )
            
            if response.status_code == 200:
                logger.info(f"✓ Sent {batch_size} URLs")
                self.stats['sent'] += batch_size
                self.url_buffer = []
            else:
                logger.error(f"✗ Server returned {response.status_code}")
                self.stats['errors'] += 1
                self.url_buffer = []
                
        except requests.exceptions.Timeout:
            logger.error(f"✗ Timeout sending to {TARGET_URL}")
            self.stats['errors'] += 1
            self.url_buffer = []
        except requests.exceptions.RequestException as e:
            logger.error(f"✗ HTTP request failed: {e}")
            self.stats['errors'] += 1
            # Keep some URLs for retry
            if len(self.url_buffer) > 100:
                self.url_buffer = self.url_buffer[-100:]
        finally:
            self.last_flush_time = time.time()
            
    def log_stats(self):
        """Log statistics periodically"""
        uptime = (datetime.now(timezone.utc) - self.stats['start_time']).total_seconds()
        rate = self.stats['processed'] / uptime if uptime > 0 else 0
        
        logger.info(
            f"📊 Processed: {self.stats['processed']}, "
            f"Sent: {self.stats['sent']}, "
            f"Deduped: {self.stats['deduped']}, "
            f"Errors: {self.stats['errors']}, "
            f"Rate: {rate:.1f}/sec"
        )
        
    def get_start_block(self, blockchain, minutes_back):
        """Calculate starting block number from minutes back"""
        try:
            # Get current block info
            info = blockchain.info()
            current_block = info['head_block_number']
            
            # Hive produces a block every 3 seconds
            # So 20 blocks per minute
            blocks_back = minutes_back * 20
            start_block = current_block - blocks_back
            
            logger.debug(f"Current block: {current_block}, Starting from block: {start_block}")
            return start_block
            
        except Exception as e:
            logger.error(f"Error calculating start block: {e}")
            # Default to a recent block if we can't calculate
            return None
            
    def run(self):
        """Main watch loop"""
        logger.info("=== PodPing Watcher Started ===")
        logger.info(f"Target: {TARGET_URL}")
        logger.info(f"Batch: {BATCH_SIZE} URLs / {BATCH_TIMEOUT}s")
        logger.info(f"Dedupe window: {DEDUPE_WINDOW}s")
        
        allowed_accounts = self.get_allowed_accounts()
        
        # Connect to blockchain with retry and better node selection
        blockchain = None
        max_retries = len(HIVE_NODES)
        
        for attempt, node in enumerate(HIVE_NODES):
            try:
                logger.info(f"Attempting connection to: {node}")
                hive = beem.Hive(node=node)
                blockchain = Blockchain(mode="head", blockchain_instance=hive)
                
                # Test the connection
                info = blockchain.info()
                logger.info(f"Connected to {node} at block {info['head_block_number']}")
                break
                
            except Exception as e:
                logger.error(f"Failed to connect to {node}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    logger.error("All Hive nodes failed!")
                    raise
        
        if not blockchain:
            raise Exception("Could not connect to any Hive node")
        
        # Calculate starting block instead of using datetime
        start_block = self.get_start_block(blockchain, LOOKBACK_MINUTES)
        
        logger.info(f"Starting from {LOOKBACK_MINUTES} minutes ago (block {start_block})")
        
        last_stats_time = time.time()
        
        try:
            # Use block number for start parameter, not datetime
            stream_params = {
                "opNames": ["custom_json"],
                "raw_ops": False,
                "threading": False
            }
            
            # Only add start if we have a valid block number
            if start_block:
                stream_params["start"] = start_block
            
            stream = blockchain.stream(**stream_params)
            
            for post in stream:
                if not self.running:
                    break
                    
                operation_id = post.get("id", "")
                if operation_id in WATCHED_OPERATION_IDS or operation_id.startswith("pp_"):
                    posting_auths = post.get("required_posting_auths", [])
                    if posting_auths and posting_auths[0] in allowed_accounts:
                        self.process_podping(post)
                        
                # Periodic flush
                if time.time() - self.last_flush_time > BATCH_TIMEOUT:
                    self.flush_urls()
                    
                # Log stats every 60 seconds
                if time.time() - last_stats_time > 60:
                    self.log_stats()
                    last_stats_time = time.time()
                    
        except Exception as e:
            logger.exception(f"Stream error: {e}")
            raise
                
        logger.info("Watcher stopped")

def main():
    """Main entry point with automatic restart"""
    logger.info("PodPing Watcher v1.1 - Production")
    
    while True:
        watcher = None
        try:
            watcher = PodPingWatcher()
            watcher.run()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            if watcher:
                watcher.flush_urls()
            break
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            logger.info("Restarting in 30 seconds...")
            time.sleep(30)

if __name__ == "__main__":
    main()