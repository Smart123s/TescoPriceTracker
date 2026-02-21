import requests
import re
import os
import time
import random
import logging
import argparse
import sys
import concurrent.futures
import threading
import json
from datetime import datetime, timedelta
from lxml import etree
from config import API_URL, HEADERS, SITEMAP_INDEX_URL
from queries import FULL_PRODUCT_QUERY, PRICE_ONLY_QUERY
import database_manager as db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- persistent run-state helpers (resume / once-per-day logic) -----------------

def _run_state_path():
    return os.path.join(db.DATA_DIR, 'run_state.json')


def _load_run_state():
    path = _run_state_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read run_state: {e}")
    return None


def _save_run_state(state: dict):
    path = _run_state_path()
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to write run_state: {e}")


def product_has_price_today(tpnc):
    """Check product JSON price_history for an entry from today.
    (No separate index — JSON-only approach.)
    """
    prod = db.get_product(tpnc)
    if not prod:
        return False
    history = prod.get('price_history', {})
    if not history:
        return False
    today = datetime.now().date()
    # Check all price sections
    for section in ['normal', 'discount', 'clubcard']:
        entries = history.get(section, [])
        for entry in reversed(entries):
            ts = entry.get('start_date')
            if not ts:
                continue
            try:
                entry_dt = datetime.fromisoformat(ts)
            except Exception:
                continue
            if entry_dt.date() == today:
                return True
    return False


def is_today_scrape_done():
    state = _load_run_state()
    if not state:
        return False
    return state.get('date') == datetime.now().date().isoformat() and state.get('completed', False)

# -----------------------------------------------------------------------------

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
    """Process single product. Returns True if the product was processed (API called / DB updated)
    and False if skipped or failed. This helps run-state resume logic.
    """
    exists = db.product_exists(tpnc)
    # If we already have today's price, skip unless forced
    if exists and not force and product_has_price_today(tpnc):
        logger.debug(f"{progress_prefix}Skipping {tpnc}: already has today's price.")
        return False
    if exists and not force:
        prod = db.get_product(tpnc)
        if prod and prod.get('last_scraped_price'):
            try:
                from dateutil import parser
                last_scraped = parser.parse(prod['last_scraped_price'])
                if (datetime.now() - last_scraped) < timedelta(hours=12):
                    return False
            except Exception as e:
                logger.warning(f"{progress_prefix}Error parsing date for {tpnc}: {e}")
    query_type = "price" if exists else "full"
    data = get_product_api(tpnc, query_type)
    if not data or 'data' not in data or not data['data']['product']:
        logger.warning(f"{progress_prefix}No data returned for {tpnc}. Response: {data}")
        return False
    product_data = data['data']['product']
    price_info = product_data.get('price')
    if not price_info:
        logger.info(f"{progress_prefix}No price info for {tpnc}, possibly unavailable.")
        return False
    price_actual = price_info.get('actual')
    unit_price = price_info.get('unitPrice')
    unit_measure = price_info.get('unitOfMeasure')
    promotions = product_data.get('promotions') or []
    # Track all types
    normal_saved = False
    discount_saved = False
    clubcard_saved = False
    # Save normal price (always present)
    normal_saved = db.insert_price(tpnc, price_actual, unit_price, unit_measure, False, None, None, None, None, None)
    # Check for discount and clubcard prices
    for promo in promotions:
        promo_id = promo.get('id')
        promo_desc = promo.get('description')
        promo_start = promo.get('startDate')
        promo_end = promo.get('endDate')
        attributes = promo.get('attributes') or []
        promo_price = None
        if promo.get('price'):
            promo_price = promo.get('price').get('afterDiscount')
        # Clubcard
        if "CLUBCARD_PRICING" in attributes:
            cc_price = promo_price
            if promo_desc:
                clean_desc = promo_desc.replace('\xa0', '').replace(' ', '')
                match = re.search(r'(\d+)Ft', clean_desc, re.IGNORECASE)
                if match:
                    parsed_price = float(match.group(1))
                    if cc_price is None or cc_price == price_actual:
                        cc_price = parsed_price
            clubcard_saved = db.insert_price(tpnc, price_actual, unit_price, unit_measure, True, promo_id, promo_desc, promo_start, promo_end, cc_price)
        else:
            # Discount (no clubcard)
            if promo_price and promo_price != price_actual:
                discount_saved = db.insert_price(tpnc, promo_price, unit_price, unit_measure, True, promo_id, promo_desc, promo_start, promo_end, None)
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
        db.upsert_product(tpnc, name, unit_measure, default_image_url, pack_size_val, pack_size_unit)
    change_status = "Changed" if (normal_saved or discount_saved or clubcard_saved) else "Unchanged"
    # Prepare log details
    log_prices = []
    log_prices.append(f"Normal: {price_actual}")
    # Find latest discount and clubcard prices
    latest_discount = None
    latest_clubcard = None
    for promo in promotions:
        attributes = promo.get('attributes') or []
        promo_price = None
        if promo.get('price'):
            promo_price = promo.get('price').get('afterDiscount')
        if "CLUBCARD_PRICING" in attributes:
            cc_price = promo_price
            promo_desc = promo.get('description')
            if promo_desc:
                clean_desc = promo_desc.replace('\xa0', '').replace(' ', '')
                match = re.search(r'(\d+)Ft', clean_desc, re.IGNORECASE)
                if match:
                    parsed_price = float(match.group(1))
                    if cc_price is None or cc_price == price_actual:
                        cc_price = parsed_price
            latest_clubcard = cc_price
        else:
            if promo_price and promo_price != price_actual:
                latest_discount = promo_price
    if latest_discount is not None:
        log_prices.append(f"Discount: {latest_discount}")
    if latest_clubcard is not None:
        log_prices.append(f"Clubcard: {latest_clubcard}")
    log_price_str = ", ".join(log_prices)
    logger.info(f"{progress_prefix}Processed {tpnc} ({change_status}). {log_price_str}")
    return True
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
    """Main entry to run the scraper with resume / once-per-day behaviour.

    Behaviour implemented:
    - single full download per calendar day (unless --force)
    - persistent run-state at `data/run_state.json` so interrupted runs resume
    - skip individual products that already have today's price entry
    - scheduler will skip starting a run if today's run is already completed
    """
    db.init_db()

    # Build full list (or use specific_items)
    if specific_items:
        all_items = list(specific_items)
        logger.info(f"Processing {len(all_items)} specific items with {threads} threads...")
    else:
        sitemaps = fetch_sitemap_index(SITEMAP_INDEX_URL)
        logger.info(f"Found {len(sitemaps)} sitemaps.")
        all_product_ids = []
        for sitemap_url in sitemaps:
            time.sleep(0.5)
            logger.info(f"Fetching products from sitemap: {sitemap_url}")
            ids = fetch_product_urls_from_sitemap(sitemap_url)
            logger.info(f"Found {len(ids)} products in {sitemap_url}")
            all_product_ids.extend(ids)
        # Remove duplicates and keep order
        all_items = list(dict.fromkeys(all_product_ids))
        logger.info(f"Total unique products discovered: {len(all_items)}")

    today_str = datetime.now().date().isoformat()

    # Load or initialize run-state for today
    state = _load_run_state() or {}
    if state.get('date') != today_str or force:
        # reset run-state for a fresh daily run (or when forced)
        state = {
            'date': today_str,
            'run_id': datetime.now().isoformat(),
            'started_at': datetime.now().isoformat(),
            'total_items': len(all_items),
            'processed': [],
            'errors': {},
            'completed': False
        }
        _save_run_state(state)

    # If today's run already completed and not forced, exit early
    if state.get('completed') and not force:
        logger.info("Today's scrape already completed — skipping run.")
        return

    # Build remaining items to process (don't re-query items that already have today's price)
    processed_set = set(state.get('processed', []))
    items_to_process = []
    for tpnc in all_items:
        if tpnc in processed_set:
            continue
        if not force and product_has_price_today(tpnc):
            # treat as already done for today's run
            processed_set.add(tpnc)
            state['processed'] = list(processed_set)
            continue
        items_to_process.append(tpnc)

    # Update total_items in state (in case sitemap changed)
    state['total_items'] = len(all_items)
    _save_run_state(state)

    if not items_to_process:
        # Nothing to do — mark completed and return
        state['completed'] = True
        state['finished_at'] = datetime.now().isoformat()
        _save_run_state(state)
        logger.info("No items to process (all up-to-date). Marked today's run as completed.")
        return

    logger.info(f"Resuming scrape: {len(items_to_process)} items to process (out of {len(all_items)} total).")

    lock = threading.Lock()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=threads)
    futures = []

    total = len(all_items)

    def _task_wrapper(idx, tpnc):
        success = False
        try:
            success = process_product(tpnc, force=force, progress_prefix=f"[{idx}/{total}] ")
        except Exception as e:
            logger.exception(f"Error processing {tpnc}: {e}")
            success = False

        # Update run-state based on actual DB state (only mark as processed when price present for today)
        with lock:
            if product_has_price_today(tpnc) or success:
                if tpnc not in state['processed']:
                    state['processed'].append(tpnc)
            else:
                # record error count
                state.setdefault('errors', {})[tpnc] = state.get('errors', {}).get(tpnc, 0) + 1
            _save_run_state(state)

    try:
        for i, tpnc in enumerate(items_to_process, 1):
            # Use absolute index within all_items to make progress prefix meaningful
            idx = all_items.index(tpnc) + 1
            futures.append(executor.submit(_task_wrapper, idx, tpnc))

        # Wait for all tasks to complete; use timeout loop so we can be responsive to interrupts
        done, not_done = concurrent.futures.wait(futures, timeout=1.0)
        while not_done:
            done, not_done = concurrent.futures.wait(futures, timeout=1.0)

    except KeyboardInterrupt:
        logger.warning("Scraping interrupted by user — saving progress and exiting gracefully...")
        # Executor shutdown will occur in finally; state already updated per-task
        return
    finally:
        if executor:
            executor.shutdown(wait=True)

    # Finalize state: mark completed only if all items were processed
    processed_count = len(state.get('processed', []))
    if processed_count >= len(all_items):
        state['completed'] = True
        state['finished_at'] = datetime.now().isoformat()
        _save_run_state(state)
        logger.info(f"Daily scrape completed: {processed_count}/{len(all_items)} items processed.")
    else:
        _save_run_state(state)
        logger.info(f"Daily scrape partial: {processed_count}/{len(all_items)} items processed — will resume on next run.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tesco Price Scraper')
    parser.add_argument('--items', nargs='+', help='List of TPNCs to scrape specifically')
    parser.add_argument('--force', action='store_true', help='Force rescrape even if recent')
    parser.add_argument('--threads', type=int, default=5, help='Number of concurrent threads (default: 5)')
    args = parser.parse_args()
    
    run_scraper(specific_items=args.items, force=args.force, threads=args.threads)
