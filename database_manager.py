import os
from datetime import datetime, timedelta
from pymongo import MongoClient
from pymongo import errors as mongo_errors
import logging

from config import MONGO_URI, MONGO_DB_NAME, MONGO_COLLECTION

logger = logging.getLogger(__name__)

# Mongo Setup
_client = None
_db = None
_collection = None

def get_db():
    global _client, _db, _collection
    if _client is None:
        _client = MongoClient(MONGO_URI)
        _db = _client[MONGO_DB_NAME]
        _collection = _db[MONGO_COLLECTION]
    return _collection

def get_runs_collection():
    get_db()
    assert _db is not None
    return _db['runs']

# Fields compared per category to detect changes
_NORMAL_FIELDS = ("price", "unit_price", "unit_measure")
_PROMO_FIELDS = ("price", "unit_price", "unit_measure",
                 "promo_id", "promo_desc", "promo_start", "promo_end")


def init_db():
    coll = get_db()
    coll.create_index([("name", "text")])
    coll.create_index("last_scraped_price")
    print("MongoDB indexes verified/created.")

def load_product_data(tpnc):
    try:
        coll = get_db()
        return coll.find_one({"_id": str(tpnc)})
    except mongo_errors.PyMongoError as e:
        logger.error(f"Error loading product {tpnc}: {e}")
        return None

def save_product_data(tpnc, data):
    try:
        coll = get_db()
        data['_id'] = str(tpnc)
        coll.replace_one({"_id": str(tpnc)}, data, upsert=True)
    except mongo_errors.PyMongoError as e:
        logger.error(f"Error saving product {tpnc}: {e}")

def product_exists(tpnc):
    coll = get_db()
    return coll.count_documents({"_id": str(tpnc)}, limit=1) > 0


def _empty_history():
    return {"normal": [], "discount": [], "clubcard": []}


# ---------------------------------------------------------------------------
# Core price insertion logic
# ---------------------------------------------------------------------------

def _compare_fields(old_entry, new_fields, category):
    """Return True if all compared fields match between old entry and new data."""
    keys = _PROMO_FIELDS if category in ("discount", "clubcard") else _NORMAL_FIELDS
    for k in keys:
        if old_entry.get(k) != new_fields.get(k):
            return False
    return True


def _is_within_frequency(end_date_str):
    """Return True if *end_date_str* (YYYY-MM-DD) is yesterday or today.

    A period written on day N can be extended on day N+1 (yesterday counts).
    Anything older than that is a gap and starts a new section.
    """
    try:
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        yesterday = (datetime.now() - timedelta(days=1)).date()
        return end_date >= yesterday
    except (ValueError, TypeError):
        return False


def _apply_period(periods, fields, category, today_str):
    """Apply period logic in-memory (no I/O). Returns True if a new entry was created."""
    if periods:
        last = periods[-1]
        same_data = _compare_fields(last, fields, category)

        if same_data and _is_within_frequency(last.get("end_date", "")):
            # Same data, recent end_date → extend the period
            last["end_date"] = today_str
            return False

        if last.get("start_date") == today_str and last.get("end_date") == today_str:
            # Data changed on the same day → overwrite with latest scrape
            last.update(fields)
            last["start_date"] = today_str
            last["end_date"] = today_str
            return True

    # No previous entry, data changed, or gap → new entry
    entry = dict(fields)
    entry["start_date"] = today_str
    entry["end_date"] = today_str
    periods.append(entry)
    return True


def insert_all_prices(tpnc, price_updates, metadata=None):
    """Insert/extend price periods for all categories in a single load/save.

    Parameters
    ----------
    tpnc : str
    price_updates : list of (category, fields) tuples
        category is "normal", "discount", or "clubcard".
    metadata : dict or None
        If provided, updates static product fields (name, unit_of_measure,
        default_image_url, pack_size_value, pack_size_unit).

    Returns
    -------
    dict: {category: bool} — True if a new section was created for that category.
    """
    data = load_product_data(tpnc)
    if not data:
        data = {"tpnc": str(tpnc), "price_history": _empty_history()}

    history = data.setdefault("price_history", _empty_history())
    today_str = datetime.now().strftime("%Y-%m-%d")

    results = {}
    for category, fields in price_updates:
        periods = history.setdefault(category, [])
        results[category] = _apply_period(periods, fields, category, today_str)

    if metadata:
        data.update(metadata)

    data["last_scraped_price"] = datetime.now().isoformat()
    save_product_data(tpnc, data)
    return results


# ---------------------------------------------------------------------------
# Query helpers (used by app.py / frontend)
# ---------------------------------------------------------------------------

def get_product(tpnc):
    return load_product_data(tpnc)


def get_price_history(tpnc):
    data = load_product_data(tpnc)
    if not data:
        return {"normal": [], "discount": [], "clubcard": []}
    history = data.get("price_history", _empty_history())
    # Return each category reversed (newest first) for display
    return {
        cat: list(reversed(entries))
        for cat, entries in history.items()
    }


def search_products(query):
    results = []
    if not query:
        return results

    coll = get_db()

    # Try text index search first
    cursor = coll.find(
        {"$text": {"$search": query}},
        {"score": {"$meta": "textScore"}}
    ).sort([("score", {"$meta": "textScore"})]).limit(20)

    results = list(cursor)

    if not results:
        # Fallback to regex scan if text doesn't match well or for tpnc
        regex_query = {"$regex": query, "$options": "i"}
        cursor = coll.find({"$or": [{"name": regex_query}, {"_id": regex_query}]}).limit(20)
        results = list(cursor)

    return results

# ---------------------------------------------------------------------------
# Run-state helpers (MongoDB-backed)
# ---------------------------------------------------------------------------

def load_run_state():
    try:
        coll = get_runs_collection()
        today_iso = datetime.now().date().isoformat()
        return coll.find_one({"_id": today_iso})
    except mongo_errors.PyMongoError as e:
        logger.warning(f"Failed to read run_state from mongo: {e}")
        return None

def save_run_state(state: dict):
    try:
        coll = get_runs_collection()
        state_id = state.get('date', datetime.now().date().isoformat())
        state['_id'] = state_id
        coll.replace_one({"_id": state_id}, state, upsert=True)
    except mongo_errors.PyMongoError as e:
        logger.error(f"Failed to write run_state to mongo: {e}")
