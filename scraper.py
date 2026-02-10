import requests
import re
import os
import time
import random
import logging
import argparse
import sys
import concurrent.futures
from datetime import datetime, timedelta
from lxml import etree
from config import API_URL, HEADERS, SITEMAP_INDEX_URL
from queries import FULL_PRODUCT_QUERY, PRICE_ONLY_QUERY
import database_manager as db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fetch_sitemap_index(url):
    try:
        response = requests.get(url, headers={'User-Agent': HEADERS['User-Agent']})
        response.raise_for_status()
        root = etree.fromstring(response.content)
        # Namespace handling for sitemaps
        namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        locs = root.xpath('//ns:loc', namespaces=namespaces)
        return [loc.text for loc in locs]
    except Exception as e:
        logger.error(f"Error fetching sitemap index: {e}")
        return []

def fetch_product_urls_from_sitemap(url):
    try:
        response = requests.get(url, headers={'User-Agent': HEADERS['User-Agent']})
        response.raise_for_status()
        root = etree.fromstring(response.content)
        namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        locs = root.xpath('//ns:loc', namespaces=namespaces)
        product_ids = []
        for loc in locs:
            # Extract ID from URL like https://bevasarlas.tesco.hu/groceries/hu-HU/products/105018735
            match = re.search(r'/products/(\d+)', loc.text)
            if match:
                product_ids.append(match.group(1))
        return product_ids
    except Exception as e:
        logger.error(f"Error fetching sitemap {url}: {e}")
        return []

def get_product_api(tpnc, query_type="full"):
    if query_type == "full":
        query = FULL_PRODUCT_QUERY
        operation_name = "GetProduct"
    else:
        query = PRICE_ONLY_QUERY
        operation_name = "GetProductPrice"

    payload_dict = {
        "operationName": operation_name,
        "variables": {
            "tpnc": str(tpnc)
        },
        "extensions": {
            "mfeName": "mfe-pdp"
        },
        "query": query
    }

    # The API expects a list of operations (batch support), even for one.
    payload = [payload_dict]

    max_retries = 5
    base_delay = 2

    for attempt in range(max_retries):
        try:
            response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=30)
            
            if response.status_code == 429:
                raise requests.exceptions.RequestException("Rate Limited (429)")

            response.raise_for_status()
            # Response is also a list
            response_json = response.json()
            if isinstance(response_json, list) and len(response_json) > 0:
                return response_json[0]
            return None
        except Exception as e:
            if attempt < max_retries - 1:
                sleep_time = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"API request failed for {tpnc} (Attempt {attempt+1}/{max_retries}). Retrying in {sleep_time:.2f}s. Error: {e}")
                time.sleep(sleep_time)
            else:
                logger.error(f"API request failed for {tpnc} after {max_retries} attempts: {e}")
                return None

def process_product(tpnc, force=False, progress_prefix=""):
    exists = db.product_exists(tpnc)
    
    if exists and not force:
        # Check if we need to update based on time
        prod = db.get_product(tpnc)
        if prod and prod.get('last_scraped_price'):
            try:
                from dateutil import parser
                last_scraped = parser.parse(prod['last_scraped_price'])
                # Only re-scrape if older than 12 hours
                if (datetime.now() - last_scraped) < timedelta(hours=12):
                    return
            except Exception as e:
                logger.warning(f"{progress_prefix}Error parsing date for {tpnc}: {e}")

    # If exists, we might want to check if we need to update static info. 
    # For now, if exists, we treat it as price update.
    # The user said: "If product was in database... simpler query"
    
    query_type = "price" if exists else "full"
    
    data = get_product_api(tpnc, query_type)
    
    if not data or 'data' not in data or not data['data']['product']:
        logger.warning(f"{progress_prefix}No data returned for {tpnc}. Response: {data}")
        return

    product_data = data['data']['product']
    
    # Extract Price Info
    price_info = product_data.get('price')
    if not price_info:
        logger.info(f"{progress_prefix}No price info for {tpnc}, possibly unavailable.")
        # Even if unavailable, we might want to record that?
        return

    price_actual = price_info.get('actual')
    unit_price = price_info.get('unitPrice')
    unit_measure = price_info.get('unitOfMeasure')
    
    # Extract Promotion Info
    promotions = product_data.get('promotions') or []
    is_promotion = False
    promo_id = None
    promo_desc = None
    promo_start = None
    promo_end = None
    clubcard_price = None

    for promo in promotions:
        # We look for the most relevant one, or just the first valid one
        # Specifically Clubcard
        if promo.get('attributes') and "CLUBCARD_PRICING" in promo.get('attributes'):
            is_promotion = True
            promo_id = promo.get('id')
            promo_desc = promo.get('description')
            promo_start = promo.get('startDate')
            promo_end = promo.get('endDate')
            
            if promo.get('price'):
                clubcard_price = promo.get('price').get('afterDiscount')
            
            # Attempt to parse price from description if needed
            # Description format: "449 Ft Clubcarddal" or "1 299 Ft Clubcarddal"
            if promo_desc:
                # Remove non-breaking spaces or simple spaces in numbers
                clean_desc = promo_desc.replace('\xa0', '').replace(' ', '')
                # Look for number followed by Ft
                match = re.search(r'(\d+)Ft', clean_desc, re.IGNORECASE)
                if match:
                    parsed_price = float(match.group(1))
                    # If parsed price differs significantly from clubcard_price (or if clubcard_price matches actual), trust description
                    if clubcard_price is None or clubcard_price == price_actual:
                         clubcard_price = parsed_price
            break # Assuming one main clubcard promo
        
        # If no clubcard, maybe a normal promo?
        if not is_promotion:
             # Take the first one if we haven't found a clubcard one yet
             # But usually price cuts are reflected in 'actual' price. 
             # Let's track metadata for any promo if we find one.
             is_promotion = True
             promo_id = promo.get('id')
             promo_desc = promo.get('description')
             promo_start = promo.get('startDate')
             promo_end = promo.get('endDate')
             if promo.get('price'):
                 # It might be a simple sale
                 pass

    # Static Data Update (if full scan)
    if query_type == "full":
        name = product_data.get('title')
        default_image_url = product_data.get('defaultImageUrl')
        
        details = product_data.get('details')
        pack_size_val = None
        pack_size_unit = None
        
        if details:
            pack_size = details.get('packSize')
            if isinstance(pack_size, list) and len(pack_size) > 0:
                pack_size_val = pack_size[0].get('value')
                pack_size_unit = pack_size[0].get('units')
            elif isinstance(pack_size, dict):
                pack_size_val = pack_size.get('value')
                pack_size_unit = pack_size.get('units')
        
        # Unit of measure from top level price object is often 'kg' or 'piece'
        # The schema uses unit_of_measure as a column.
        
        db.upsert_product(tpnc, name, unit_measure, default_image_url, pack_size_val, pack_size_unit)

    # Insert Price History
    inserted = db.insert_price(tpnc, price_actual, unit_price, unit_measure, is_promotion, promo_id, promo_desc, promo_start, promo_end, clubcard_price)
    
    change_status = "Changed" if inserted else "Unchanged"
    promo_text = f" | Promo: {promo_desc} (CC: {clubcard_price})" if is_promotion else ""
    logger.info(f"{progress_prefix}Processed {tpnc} ({change_status}). Price: {price_actual}{promo_text}")

def run_scraper(specific_items=None, force=False, threads=5):
    db.init_db()
    executor = None
    futures = []
    
    try:
        items_to_process = []
        
        if specific_items:
            items_to_process = specific_items
            logger.info(f"Processing {len(items_to_process)} specific items with {threads} threads...")
        else:
            sitemaps = fetch_sitemap_index(SITEMAP_INDEX_URL)
            logger.info(f"Found {len(sitemaps)} sitemaps.")
            
            all_product_ids = []
            for sitemap_url in sitemaps:
                logger.info(f"Fetching products from sitemap: {sitemap_url}")
                ids = fetch_product_urls_from_sitemap(sitemap_url)
                logger.info(f"Found {len(ids)} products in {sitemap_url}")
                all_product_ids.extend(ids)
            
            # Remove duplicates
            all_product_ids = list(dict.fromkeys(all_product_ids))
            items_to_process = all_product_ids
            logger.info(f"Total unique products to process: {len(items_to_process)}")
            logger.info(f"Starting scrape with {threads} threads...")

        total = len(items_to_process)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=threads)
        
        for i, tpnc in enumerate(items_to_process, 1):
            futures.append(executor.submit(process_product, tpnc, force=force, progress_prefix=f"[{i}/{total}] "))
        
        # Wait for all tasks to complete
        # We use a loop with timeout to allow KeyboardInterrupt to be caught on Windows
        done, not_done = concurrent.futures.wait(futures, timeout=1.0)
        while not_done:
            done, not_done = concurrent.futures.wait(futures, timeout=1.0)

    except KeyboardInterrupt:
        logger.warning("\nScraping interrupted by user. Stopping threads...")
        if executor:
            # Cancel all pending futures
            for f in futures:
                if not f.running() and not f.done():
                    f.cancel()
            executor.shutdown(wait=False)
        # Force immediate exit, bypassing cleanup that waits for threads
        os._exit(0)
    finally:
        if executor:
            executor.shutdown(wait=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tesco Price Scraper')
    parser.add_argument('--items', nargs='+', help='List of TPNCs to scrape specifically')
    parser.add_argument('--force', action='store_true', help='Force rescrape even if recent')
    parser.add_argument('--threads', type=int, default=5, help='Number of concurrent threads (default: 5)')
    args = parser.parse_args()
    
    run_scraper(specific_items=args.items, force=args.force, threads=args.threads)
