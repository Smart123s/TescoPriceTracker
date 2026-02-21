import json
import os
import glob
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load .env into environment (does NOT override existing environment vars by default)
load_dotenv()

DATA_FOLDER_ENV = os.getenv('DATA_FOLDER', '/app/data')
if DATA_FOLDER_ENV:
    DATA_DIR = os.path.abspath(DATA_FOLDER_ENV)
else:
    # 2) detect virtualenv: prefer VIRTUAL_ENV env var, otherwise check sys.prefix/base_prefix
    venv_path = os.getenv('VIRTUAL_ENV') or (sys.prefix if getattr(sys, 'base_prefix', sys.prefix) != sys.prefix else None)
    if venv_path:
        # keep data inside the active virtualenv
        DATA_DIR = os.path.abspath(os.path.join(venv_path, 'data'))
    else:
        print("Error, no environment variable DATA_FOLDER set and no virtualenv detected. Please set DATA_FOLDER to a valid path.")
        sys.exit(1)
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

def upsert_product(tpnc, name, unit_of_measure, default_image_url, pack_size_value, pack_size_unit):
    data = load_product_data(tpnc)
    if not data:
        data = {
            "tpnc": str(tpnc),
            "price_history": {
                "normal": [],
                "discount": [],
                "clubcard": []
            }
        }
    data.update({
        "name": name,
        "unit_of_measure": unit_of_measure,
        "default_image_url": default_image_url,
        "pack_size_value": pack_size_value,
        "pack_size_unit": pack_size_unit,
        "last_scraped_static": datetime.now().isoformat(),
        "last_scraped_price": data.get("last_scraped_price")
    })
    if not data["last_scraped_price"]:
        data["last_scraped_price"] = datetime.now().isoformat()
    save_product_data(tpnc, data)

def insert_price(tpnc, price_actual, unit_price, unit_measure, is_promotion, promotion_id, promotion_desc, promo_start, promo_end, clubcard_price):
    data = load_product_data(tpnc)
    if not data:
        data = {
            "tpnc": str(tpnc),
            "price_history": {
                "normal": [],
                "discount": [],
                "clubcard": []
            }
        }
    history = data.get("price_history", {
        "normal": [],
        "discount": [],
        "clubcard": []
    })
    now = datetime.now()
    now_str = now.isoformat()
    yesterday = (now - timedelta(days=1)).date()

    def update_period(section, price, extra):
        periods = history[section]
        if periods:
            last = periods[-1]
            last_price = last["price"]
            last_end = last["end_date"]
            # If price unchanged and last_end is yesterday or today, extend period
            if last_price == price:
                last_end_dt = datetime.fromisoformat(last_end) if last_end else None
                if last_end_dt and last_end_dt.date() >= yesterday:
                    last["end_date"] = now_str
                    return False
        # New period
        period = {"price": price, "start_date": now_str, "end_date": None}
        period.update(extra)
        periods.append(period)
        return True

    changed = False
    # Normal price
    if not is_promotion and not clubcard_price:
        changed = update_period("normal", price_actual, {
            "unit_price": unit_price,
            "unit_measure": unit_measure
        }) or changed
    # Discount price (no clubcard)
    if is_promotion and not clubcard_price:
        changed = update_period("discount", price_actual, {
            "unit_price": unit_price,
            "unit_measure": unit_measure,
            "promo_id": promotion_id,
            "promo_desc": promotion_desc,
            "promo_start": promo_start,
            "promo_end": promo_end
        }) or changed
    # Clubcard price
    if clubcard_price:
        changed = update_period("clubcard", clubcard_price, {
            "unit_price": unit_price,
            "unit_measure": unit_measure,
            "promo_id": promotion_id,
            "promo_desc": promotion_desc,
            "promo_start": promo_start,
            "promo_end": promo_end
        }) or changed
    data["price_history"] = history
    data["last_scraped_price"] = now_str
    save_product_data(tpnc, data)
    return changed

def update_last_scraped_price(tpnc):
    data = load_product_data(tpnc)
    if data:
        data['last_scraped_price'] = datetime.now().isoformat()
        save_product_data(tpnc, data)

def get_product(tpnc):
    return load_product_data(tpnc)

def get_price_history(tpnc):
    data = load_product_data(tpnc)
    if data:
        # Return reversed history to simulate ORDER BY timestamp DESC
        return list(reversed(data.get('price_history', [])))
    return []

def search_products(query):
    results = []
    if not query:
        return results
        
    query = query.lower()
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    
    for file_path in files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                name = data.get('name', '')
                tpnc = data.get('tpnc', '')
                
                match = False
                if name and query in name.lower():
                    match = True
                if tpnc and query in str(tpnc):
                    match = True
                    
                if match:
                    results.append(data)
                    if len(results) >= 20: 
                        break
        except Exception:
            continue
    return results
