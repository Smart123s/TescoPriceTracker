import json
import os
import glob
from datetime import datetime

DATA_DIR = 'data'

def init_db():
    if not os.path.exists(DATA_DIR):
        print("Initializing data directory...")
        os.makedirs(DATA_DIR)
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
            "price_history": []
        }
    
    data.update({
        "name": name,
        "unit_of_measure": unit_of_measure,
        "default_image_url": default_image_url,
        "pack_size_value": pack_size_value,
        "pack_size_unit": pack_size_unit,
        "last_scraped_static": datetime.now().isoformat(),
        # Init last_scraped_price if missing
        "last_scraped_price": data.get("last_scraped_price") 
    })
    
    if not data["last_scraped_price"]:
        data["last_scraped_price"] = datetime.now().isoformat()

    save_product_data(tpnc, data)

def insert_price(tpnc, price_actual, unit_price, unit_measure, is_promotion, promotion_id, promotion_desc, promo_start, promo_end, clubcard_price):
    data = load_product_data(tpnc)
    if not data:
        data = { "tpnc": str(tpnc), "price_history": [] }

    history = data.get("price_history", [])
    
    should_insert = True
    if history:
        last_entry = history[-1]
        
        old_actual = last_entry.get('price_actual')
        old_cc = last_entry.get('clubcard_price')
        old_promo = last_entry.get('is_promotion')
        old_desc = last_entry.get('promotion_description')
        
        # Simple comparison
        if (old_actual == price_actual and 
            old_cc == clubcard_price and 
            old_promo == is_promotion and 
            old_desc == promotion_desc):
            should_insert = False

    if should_insert:
        # Handle promo dates which might be strings or datetime objects
        p_start = promo_start
        if hasattr(promo_start, 'isoformat'):
            p_start = promo_start.isoformat()
            
        p_end = promo_end
        if hasattr(promo_end, 'isoformat'):
            p_end = promo_end.isoformat()

        new_entry = {
            "timestamp": datetime.now().isoformat(),
            "price_actual": price_actual,
            "unit_price": unit_price,
            "unit_measure": unit_measure,
            "is_promotion": is_promotion,
            "promotion_id": promotion_id,
            "promotion_description": promotion_desc,
            "promotion_start": p_start,
            "promotion_end": p_end,
            "clubcard_price": clubcard_price
        }
        history.append(new_entry)
        data['price_history'] = history
    
    data['last_scraped_price'] = datetime.now().isoformat()
    save_product_data(tpnc, data)
    return should_insert

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
