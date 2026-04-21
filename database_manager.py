import os
from datetime import datetime
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


# ---------------------------------------------------------------------------
# Daily price insertion logic
# ---------------------------------------------------------------------------

def insert_daily_prices(tpnc, price_updates, metadata=None):
    """Store prices for today as a daily snapshot.

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
    dict: {category: bool} — True if a new day entry was created, False if updated.
    """
    data = load_product_data(tpnc)
    if not data:
        data = {"tpnc": str(tpnc), "price_history": []}

    history = data.setdefault("price_history", [])
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Find today's entry or create a blank one
    today_entry = None
    for entry in history:
        if entry.get("date") == today_str:
            today_entry = entry
            break

    is_new_day = today_entry is None
    if is_new_day:
        today_entry = {"date": today_str, "normal": None, "discount": None, "clubcard": None}
        history.append(today_entry)

    for category, fields in price_updates:
        today_entry[category] = dict(fields)

    if metadata:
        data.update(metadata)

    data["last_scraped_price"] = datetime.now().isoformat()
    save_product_data(tpnc, data)

    return {category: is_new_day for category, _ in price_updates}


# ---------------------------------------------------------------------------
# Query helpers (used by app.py / frontend)
# ---------------------------------------------------------------------------

def get_product(tpnc):
    return load_product_data(tpnc)


def get_price_history(tpnc):
    data = load_product_data(tpnc)
    if not data:
        return []
    history = data.get("price_history", [])
    # Return newest first
    return list(reversed(history))


def get_all_product_ids(skip=0, limit=100):
    """Return paginated list of all product TPNCs.

    Returns
    -------
    dict with keys: ids (list of str), total (int), skip (int), limit (int)
    """
    coll = get_db()
    assert coll is not None
    total = coll.count_documents({})
    cursor = coll.find({}, {"_id": 1}).skip(skip).limit(limit)
    ids = [doc["_id"] for doc in cursor]
    return {"ids": ids, "total": total, "skip": skip, "limit": limit}


def get_product_stats(tpnc):
    """Compute min/max/avg/current price per category across all daily history.

    Returns
    -------
    dict or None if product not found.
    """
    data = load_product_data(tpnc)
    if not data:
        return None

    history = data.get("price_history", [])

    stats = {}
    for category in ("normal", "discount", "clubcard"):
        prices = [
            entry[category]["price"]
            for entry in history
            if entry.get(category) and entry[category].get("price") is not None
        ]
        if not prices:
            stats[category] = None
        else:
            stats[category] = {
                "min_price": min(prices),
                "max_price": max(prices),
                "avg_price": round(sum(prices) / len(prices), 2),
                "current_price": prices[-1],  # history is oldest-first in storage
            }

    sorted_history = sorted(history, key=lambda e: e.get("date", ""))
    first_date = sorted_history[0]["date"] if sorted_history else None
    last_date = sorted_history[-1]["date"] if sorted_history else None

    return {
        "tpnc": str(tpnc),
        "name": data.get("name"),
        "total_days": len(history),
        "first_date": first_date,
        "last_date": last_date,
        "normal": stats["normal"],
        "discount": stats["discount"],
        "clubcard": stats["clubcard"],
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
