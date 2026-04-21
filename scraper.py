import requests
import re
import time
import random
import logging
import argparse
import concurrent.futures
import threading
from datetime import datetime
from lxml import etree  # type: ignore[import-untyped]
from config import API_URL, HEADERS, SITEMAP_INDEX_URL, DEFAULT_THREADS
from queries import FULL_PRODUCT_QUERY, PRICE_ONLY_QUERY
import database_manager as db
import stats_manager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skip-check: reads from MongoDB, no local file fallback.
# ---------------------------------------------------------------------------

def needs_scraping(tpnc):
    """Return True if *tpnc* has not been scraped today (calendar-day check)."""
    prod = db.get_product(tpnc)
    if not prod:
        return True
    last_scraped = prod.get('last_scraped_price')
    if not last_scraped:
        return True
    try:
        last_date = datetime.fromisoformat(last_scraped).date()
        return last_date < datetime.now().date()
    except (ValueError, AttributeError):
        return True


def is_today_scrape_done():
    """Advisory check used by the scheduler loop only."""
    state = db.load_run_state()
    if not state:
        return False
    return (state.get('date') == datetime.now().date().isoformat()
            and state.get('completed', False))


# ---------------------------------------------------------------------------
# Sitemap fetching
# ---------------------------------------------------------------------------

def fetch_sitemap_index(url):
    try:
        response = requests.get(url, headers={'User-Agent': HEADERS['User-Agent']}, timeout=30)
        response.raise_for_status()
        root = etree.fromstring(response.content)
        namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        locs = root.xpath('//ns:loc', namespaces=namespaces)
        return [loc.text for loc in locs]
    except (requests.RequestException, etree.XMLSyntaxError, OSError) as e:
        logger.error(f"Error fetching sitemap index: {e}")
        return []


def fetch_product_urls_from_sitemap(url):
    try:
        response = requests.get(url, headers={'User-Agent': HEADERS['User-Agent']}, timeout=30)
        response.raise_for_status()
        root = etree.fromstring(response.content)
        namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        locs = root.xpath('//ns:loc', namespaces=namespaces)
        product_ids = []
        for loc in locs:
            match = re.search(r'/products/(\d+)', loc.text)
            if match:
                product_ids.append(match.group(1))
        return product_ids
    except (requests.RequestException, etree.XMLSyntaxError, OSError) as e:
        logger.error(f"Error fetching sitemap {url}: {e}")
        return []


# ---------------------------------------------------------------------------
# Tesco GraphQL API call with exponential backoff
# ---------------------------------------------------------------------------

def get_product_api(tpnc, query_type="full"):
    if query_type == "full":
        query = FULL_PRODUCT_QUERY
        operation_name = "GetProduct"
    else:
        query = PRICE_ONLY_QUERY
        operation_name = "GetProductPrice"

    payload = [{
        "operationName": operation_name,
        "variables": {"tpnc": str(tpnc)},
        "extensions": {"mfeName": "mfe-pdp"},
        "query": query,
    }]

    max_retries = 5
    base_delay = 2

    for attempt in range(max_retries):
        try:
            response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=30)
            if response.status_code == 429:
                raise requests.RequestException("Rate Limited (429)")
            response.raise_for_status()
            response_json = response.json()
            if isinstance(response_json, list) and len(response_json) > 0:
                return response_json[0]
            return None
        except (requests.RequestException, ValueError) as e:
            if attempt < max_retries - 1:
                sleep_time = base_delay * (2 ** attempt) + random.uniform(0, 1)
                if "Max retries exceeded" in str(e):
                    sleep_time = 3
                logger.warning(f"API request failed for {tpnc} (Attempt {attempt+1}/{max_retries}). "
                               f"Retrying in {sleep_time:.2f}s. Error: {e}")
                time.sleep(sleep_time)
            else:
                logger.error(f"API request failed for {tpnc} after {max_retries} attempts: {e}")
                if "Max retries exceeded" in str(e):
                    time.sleep(3)
                return None


# ---------------------------------------------------------------------------
# Process a single product
# ---------------------------------------------------------------------------

def process_product(tpnc, force=False, progress_prefix=""):
    """Fetch data for *tpnc* and store prices in all applicable categories.

    Returns True if the product was processed (API called), False if skipped/failed.
    """
    exists = db.product_exists(tpnc)

    if exists and not force and not needs_scraping(tpnc):
        logger.debug(f"{progress_prefix}Skipping {tpnc}: already up-to-date.")
        return False

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

    # ---- Build price updates list (normal always included) ----
    price_updates = [("normal", {
        "price": price_actual,
        "unit_price": unit_price,
        "unit_measure": unit_measure,
    })]

    for promo in promotions:
        promo_id = promo.get('id')
        promo_desc = promo.get('description')
        promo_start = promo.get('startDate')
        promo_end = promo.get('endDate')
        attributes = promo.get('attributes') or []
        promo_price = None
        if promo.get('price'):
            promo_price = promo['price'].get('afterDiscount')

        if "CLUBCARD_PRICING" in attributes:
            cc_price = promo_price
            if promo_desc:
                clean_desc = promo_desc.replace('\xa0', '').replace(' ', '')
                match = re.search(r'(\d+)Ft', clean_desc, re.IGNORECASE)
                if match:
                    parsed_price = float(match.group(1))
                    if cc_price is None or cc_price == price_actual:
                        cc_price = parsed_price
            price_updates.append(("clubcard", {
                "price": cc_price,
                "unit_price": unit_price,
                "unit_measure": unit_measure,
                "promo_id": promo_id,
                "promo_desc": promo_desc,
                "promo_start": promo_start,
                "promo_end": promo_end,
            }))
        else:
            if promo_price and promo_price != price_actual:
                price_updates.append(("discount", {
                    "price": promo_price,
                    "unit_price": unit_price,
                    "unit_measure": unit_measure,
                    "promo_id": promo_id,
                    "promo_desc": promo_desc,
                    "promo_start": promo_start,
                    "promo_end": promo_end,
                }))

    # ---- Build metadata dict on first fetch ----
    metadata = None
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
        metadata = {
            "name": name,
            "unit_of_measure": unit_measure,
            "default_image_url": default_image_url,
            "pack_size_value": pack_size_val,
            "pack_size_unit": pack_size_unit,
        }

    # ---- Single load/save for all categories + optional metadata ----
    results = db.insert_daily_prices(tpnc, price_updates, metadata=metadata)

    # ---- Logging ----
    change_status = "Changed" if any(results.values()) else "Unchanged"
    log_prices = [f"Normal: {price_actual}"]
    for category, fields in price_updates:
        if category == "discount":
            log_prices.append(f"Discount: {fields['price']}")
        elif category == "clubcard":
            log_prices.append(f"Clubcard: {fields['price']}")

    logger.info(f"{progress_prefix}Processed {tpnc} ({change_status}). {', '.join(log_prices)}")
    return True


# ---------------------------------------------------------------------------
# Main scraper entry point
# ---------------------------------------------------------------------------

def run_scraper(specific_items=None, force=False, threads=DEFAULT_THREADS):
    """Run the scraper.

    - specific_items provided: always scrapes those items (no skip check).
    - No specific_items: skips products already scraped today (calendar-day).
    - force=True: scrapes everything regardless.
    """
    db.init_db()

    # ---- Build product ID list ----
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
        # Deduplicate
        all_items = list(dict.fromkeys(all_product_ids))
        logger.info(f"Total unique products discovered: {len(all_items)}")

    # ---- Sort by ascending numeric ID (lowest first) ----
    all_items.sort(key=lambda x: int(x))

    # ---- Filter: check each product in parallel ----
    # specific_items runs always; full runs skip products already done today.
    if force or specific_items:
        items_to_process = list(all_items)
    else:
        logger.info("Checking which products need scraping (parallel DB reads)...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as check_pool:
            check_results = list(check_pool.map(
                lambda tpnc: (tpnc, needs_scraping(tpnc)), all_items
            ))
        items_to_process = [tpnc for tpnc, needed in check_results if needed]

    logger.info(f"{len(items_to_process)} items to process (out of {len(all_items)} total).")

    if not items_to_process:
        logger.info("All products are up-to-date. Nothing to do.")
        db.save_run_state({
            'date': datetime.now().date().isoformat(),
            'total_items': len(all_items),
            'processed_count': len(all_items),
            'completed': True,
            'finished_at': datetime.now().isoformat(),
        })
        return

    # ---- Initialize advisory run-state ----
    state = {
        'date': datetime.now().date().isoformat(),
        'run_id': datetime.now().isoformat(),
        'started_at': datetime.now().isoformat(),
        'total_items': len(all_items),
        'processed_count': len(all_items) - len(items_to_process),
        'errors': {},
        'completed': False,
    }
    db.save_run_state(state)

    # ---- Process items with thread pool ----
    lock = threading.Lock()
    total = len(all_items)
    # Pre-build index to avoid O(n²) .index() calls inside the loop
    item_index = {tpnc: i + 1 for i, tpnc in enumerate(all_items)}

    def _task_wrapper(idx, tpnc):
        success = False
        try:
            success = process_product(tpnc, force=force,
                                      progress_prefix=f"[{idx}/{total}] ")
        except Exception as e:
            logger.exception(f"Unhandled error processing {tpnc}: {e}")

        with lock:
            if success or not needs_scraping(tpnc):
                state['processed_count'] = state.get('processed_count', 0) + 1
            else:
                state.setdefault('errors', {})[tpnc] = \
                    state.get('errors', {}).get(tpnc, 0) + 1
        # DB write outside the lock to avoid blocking other threads during I/O
        db.save_run_state(state)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=threads)
    futures = []
    try:
        for tpnc in items_to_process:
            idx = item_index[tpnc]
            futures.append(executor.submit(_task_wrapper, idx, tpnc))

        _, not_done = concurrent.futures.wait(futures, timeout=1.0)
        while not_done:
            _, not_done = concurrent.futures.wait(futures, timeout=1.0)

    except KeyboardInterrupt:
        logger.warning("Scraping interrupted — progress saved.")
        return
    finally:
        executor.shutdown(wait=True)

    # ---- Finalize run-state ----
    processed = state.get('processed_count', 0)
    if processed >= len(all_items):
        state['completed'] = True
        state['finished_at'] = datetime.now().isoformat()
        db.save_run_state(state)
        logger.info(f"Daily scrape completed: {processed}/{len(all_items)} items.")
        logger.info("Rebuilding stats cache...")
        stats_manager.rebuild_all_cache()
    else:
        db.save_run_state(state)
        logger.info(f"Daily scrape partial: {processed}/{len(all_items)} items — will resume on next run.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tesco Price Scraper')
    parser.add_argument('--items', nargs='+', help='List of TPNCs to scrape')
    parser.add_argument('--force', action='store_true', help='Force rescrape')
    parser.add_argument('--threads', type=int, default=DEFAULT_THREADS,
                        help=f'Concurrent threads (default: {DEFAULT_THREADS})')
    args = parser.parse_args()
    run_scraper(specific_items=args.items, force=args.force, threads=args.threads)
