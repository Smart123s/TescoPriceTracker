import json
import os
import glob
from datetime import datetime, timedelta
from config import DATA_DIR, SCRAPE_FREQUENCY_MINUTES

# Fields compared per category to detect changes
_NORMAL_FIELDS = ("price", "unit_price", "unit_measure")
_PROMO_FIELDS = ("price", "unit_price", "unit_measure",
                 "promo_id", "promo_desc", "promo_start", "promo_end")


def init_db():
    if not os.path.exists(DATA_DIR):
        print(f"Initializing data directory at {DATA_DIR}...")
        os.makedirs(DATA_DIR, exist_ok=True)
        print("Data directory initialized.")


def get_product_file_path(tpnc):
    return os.path.join(DATA_DIR, f"{tpnc}.json")


def load_product_data(tpnc):
    path = get_product_file_path(tpnc)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading product {tpnc}: {e}")
        return None


def save_product_data(tpnc, data):
    path = get_product_file_path(tpnc)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving product {tpnc}: {e}")


def product_exists(tpnc):
    return os.path.exists(get_product_file_path(tpnc))


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
    """Return True if *end_date_str* (YYYY-MM-DD) is recent enough to extend."""
    try:
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        diff_minutes = (datetime.now() - end_date).total_seconds() / 60
        return diff_minutes <= (SCRAPE_FREQUENCY_MINUTES + 1440)
    except Exception:
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

    query = query.lower()
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))

    for file_path in files:
        # Skip non-product files (e.g. run_state.json)
        basename = os.path.basename(file_path)
        if not basename[0].isdigit():
            continue
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                name = data.get('name', '')
                tpnc = data.get('tpnc', '')

                if (name and query in name.lower()) or (tpnc and query in str(tpnc)):
                    results.append(data)
                    if len(results) >= 20:
                        break
        except Exception:
            continue
    return results
