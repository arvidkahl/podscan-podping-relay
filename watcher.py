#!/usr/bin/env python3
"""
PodPing Watcher for Podscan.fm - Production Fixed Version
Handles datetime properly and connects reliably to Hive
"""

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Set, List, Dict, Any

import beem
from beem.account import Account
from beem.blockchain import Blockchain
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# Load configuration with proper trimming
def get_env(key, default):
    """Get environment variable with whitespace trimming"""
    value = os.environ.get(key, default)
    if isinstance(value, str):
        value = value.strip()
    return value

# Configuration from environment
TARGET_URL = get_env('TARGET_URL', 'http://localhost:8080/-/podping')
LOOKBACK_MINUTES = int(get_env('LOOKBACK_MINUTES', '5'))
BATCH_SIZE = int(get_env('BATCH_SIZE', '50'))
BATCH_TIMEOUT = int(get_env('BATCH_TIMEOUT', '3'))
DEDUPE_WINDOW = int(get_env('DEDUPE_WINDOW', '30'))
LOG_LEVEL = get_env('LOG_LEVEL', 'INFO')

# Hive nodes - use the most reliable ones
HIVE_NODES = get_env('HIVE_NODES', ','.join([
    "https://api.deathwing.me",
    "https://hive-api.arcange.eu",
    "https://rpc.ecency.com",
    "https://api.hive.blog",
    "https://hived.emre.sh",
    "https://api.openhive.network",
])).split(',')

# Clean up node URLs
HIVE_NODES = [node.strip() for node in HIVE_NODES if node.strip()]

# Constants
WATCHED_OPERATION_IDS = ["podping", "pp_", "pplt_"]

# Logging configuration
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Log configuration at startup
logger.info(f"Configuration loaded:")
logger.info(f"  TARGET_URL: {TARGET_URL}")
logger.info(f"  BATCH_SIZE: {BATCH_SIZE}")
logger.info(f"  BATCH_TIMEOUT: {BATCH_TIMEOUT}s")
logger.info(f"  DEDUPE_WINDOW: {DEDUPE_WINDOW}s")
logger.info(f"  LOOKBACK_MINUTES: {LOOKBACK_MINUTES}")
logger.info(f"  HIVE_NODES: {len(HIVE_NODES)} nodes configured")

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
        
    def get_allowed_accounts(self) -> Set[str]:
        """Get list of accounts authorized to send podpings"""
        # For now, use a comprehensive fallback list
        # The follow_api issue is affecting all nodes
        logger.info("Using fallback account list due to API issues")
        return {
            "podping", "podping.aaa", "podping.bbb", 
            "podping.ccc", "podping.ddd", "podping.eee",
            "podping.fff", "podping.ggg", "podping.hhh",
            "hivehydra", "podstation", "podping-bbb",
            "podping-ccc", "podping-ddd", "podping-eee",
            "podping-fff", "podping-ggg"
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
            
            # Extract URLs - handle multiple formats
            urls = []
            
            # Check for 'urls' field (array)
            if "urls" in json_data:
                url_data = json_data.get("urls", [])
                if isinstance(url_data, list):
                    urls.extend(url_data)
                elif isinstance(url_data, str):
                    urls.append(url_data)
            
            # Check for 'url' field (singular)
            if "url" in json_data:
                url = json_data.get("url")
                if url and isinstance(url, str):
                    urls.append(url)
            
            # Check for 'iris' field (legacy format)
            if "iris" in json_data:
                iris_data = json_data.get("iris", [])
                if isinstance(iris_data, list):
                    urls.extend(iris_data)
            
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
                logger.info(f"✓ Sent {batch_size} URLs to {TARGET_URL}")
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
            info = blockchain.info()
            current_block = info['head_block_number']
            
            # Hive produces a block every 3 seconds = 20 blocks per minute
            blocks_back = minutes_back * 20
            start_block = max(1, current_block - blocks_back)
            
            logger.debug(f"Current block: {current_block}, Starting from block: {start_block}")
            return start_block
            
        except Exception as e:
            logger.error(f"Error calculating start block: {e}")
            return None
            
    def run(self):
        """Main watch loop"""
        logger.info("=== PodPing Watcher Started ===")
        logger.info(f"Target: {TARGET_URL}")
        logger.info(f"Batch: {BATCH_SIZE} URLs / {BATCH_TIMEOUT}s")
        logger.info(f"Dedupe window: {DEDUPE_WINDOW}s")
        
        allowed_accounts = self.get_allowed_accounts()
        logger.info(f"Monitoring {len(allowed_accounts)} accounts")
        
        # Connect to blockchain with retry
        blockchain = None
        connected_node = None
        
        for node in HIVE_NODES:
            try:
                logger.info(f"Attempting connection to: {node}")
                hive = beem.Hive(node=node)
                blockchain = Blockchain(mode="head", blockchain_instance=hive)
                
                # Test the connection
                info = blockchain.info()
                logger.info(f"✓ Connected to {node} at block {info['head_block_number']}")
                connected_node = node
                break
                
            except Exception as e:
                logger.warning(f"Failed to connect to {node}: {e}")
                continue
        
        if not blockchain:
            raise Exception("Could not connect to any Hive node")
        
        # Calculate starting block
        start_block = self.get_start_block(blockchain, LOOKBACK_MINUTES)
        
        if start_block:
            logger.info(f"Starting from block {start_block} ({LOOKBACK_MINUTES} minutes ago)")
        else:
            logger.info("Starting from current block")
        
        last_stats_time = time.time()
        reconnect_attempts = 0
        max_reconnect_attempts = 5
        
        while self.running:
            try:
                # Set up stream parameters
                stream_params = {
                    "opNames": ["custom_json"],
                    "raw_ops": False,
                    "threading": False
                }
                
                if start_block:
                    stream_params["start"] = start_block
                
                stream = blockchain.stream(**stream_params)
                reconnect_attempts = 0  # Reset on successful connection
                
                for post in stream:
                    if not self.running:
                        break
                        
                    operation_id = post.get("id", "")
                    if operation_id in WATCHED_OPERATION_IDS or operation_id.startswith("pp"):
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
                logger.error(f"Stream error: {e}")
                reconnect_attempts += 1
                
                if reconnect_attempts >= max_reconnect_attempts:
                    logger.error(f"Max reconnection attempts reached")
                    raise
                    
                logger.info(f"Attempting to reconnect (attempt {reconnect_attempts}/{max_reconnect_attempts})")
                time.sleep(5 * reconnect_attempts)
                
                # Try to reconnect
                try:
                    blockchain = Blockchain(mode="head", blockchain_instance=hive)
                    start_block = None  # Start from current on reconnect
                    logger.info("Reconnected successfully")
                except Exception as re:
                    logger.error(f"Reconnection failed: {re}")
                    continue
                
        logger.info("Watcher stopped")

def main():
    """Main entry point with automatic restart"""
    logger.info("PodPing Watcher v1.2 - Production")
    
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