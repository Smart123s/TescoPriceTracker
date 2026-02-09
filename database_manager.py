import sqlite3
import os
from datetime import datetime

DB_FILE = 'database.db'
SCHEMA_FILE = 'schema.sql'

def get_db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if not os.path.exists(DB_FILE):
        print("Initializing database...")
        conn = get_db_connection()
        with open(SCHEMA_FILE, 'r') as f:
            conn.executescript(f.read())
        conn.commit()
        conn.close()
        print("Database initialized.")
    else:
        # Ensure schema is applied if db exists but tables might be missing (simple check)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
        if not cursor.fetchone():
             with open(SCHEMA_FILE, 'r') as f:
                conn.executescript(f.read())
        conn.close()

def product_exists(tpnc):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM products WHERE tpnc = ?", (tpnc,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists

def upsert_product(tpnc, name, unit_of_measure, default_image_url, pack_size_value, pack_size_unit):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO products (tpnc, name, unit_of_measure, default_image_url, pack_size_value, pack_size_unit, last_scraped_static, last_scraped_price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tpnc) DO UPDATE SET
            name=excluded.name,
            unit_of_measure=excluded.unit_of_measure,
            default_image_url=excluded.default_image_url,
            pack_size_value=excluded.pack_size_value,
            pack_size_unit=excluded.pack_size_unit,
            last_scraped_static=excluded.last_scraped_static
    """, (tpnc, name, unit_of_measure, default_image_url, pack_size_value, pack_size_unit, datetime.now(), datetime.now()))
    conn.commit()
    conn.close()

def insert_price(tpnc, price_actual, unit_price, unit_measure, is_promotion, promotion_id, promotion_desc, promo_start, promo_end, clubcard_price):
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Check for existing latest entry to avoid duplicates if data hasn't changed
    cur.execute("""
        SELECT price_actual, clubcard_price, is_promotion, promotion_description 
        FROM price_history 
        WHERE tpnc = ? 
        ORDER BY id DESC 
        LIMIT 1
    """, (tpnc,))
    last_entry = cur.fetchone()
    
    should_insert = True
    if last_entry:
        old_actual = last_entry['price_actual']
        old_cc = last_entry['clubcard_price']
        old_promo = bool(last_entry['is_promotion'])
        old_desc = last_entry['promotion_description']
        
        # Treat None and empty string as similar for description comparison if needed, 
        # but exact match is safer.
        
        if (old_actual == price_actual and 
            old_cc == clubcard_price and 
            old_promo == is_promotion and 
            old_desc == promotion_desc):
            should_insert = False

    if should_insert:
        cur.execute("""
            INSERT INTO price_history 
            (tpnc, timestamp, price_actual, unit_price, unit_measure, is_promotion, promotion_id, promotion_description, promotion_start, promotion_end, clubcard_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (tpnc, datetime.now(), price_actual, unit_price, unit_measure, is_promotion, promotion_id, promotion_desc, promo_start, promo_end, clubcard_price))
    
    # Always update last_scraped_price in products table so we know we checked it
    cur.execute("UPDATE products SET last_scraped_price = ? WHERE tpnc = ?", (datetime.now(), tpnc))
    
    conn.commit()
    conn.close()
    return should_insert

def update_last_scraped_price(tpnc):
     conn = get_db_connection()
     cur = conn.cursor()
     cur.execute("UPDATE products SET last_scraped_price = ? WHERE tpnc = ?", (datetime.now(), tpnc))
     conn.commit()
     conn.close()

def get_product(tpnc):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE tpnc = ?", (tpnc,))
    prod = cur.fetchone()
    conn.close()
    return prod

def get_price_history(tpnc):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM price_history WHERE tpnc = ? ORDER BY timestamp DESC", (tpnc,))
    rows = cur.fetchall()
    conn.close()
    return rows

def search_products(query):
    conn = get_db_connection()
    cur = conn.cursor()
    search = f"%{query}%"
    cur.execute("SELECT * FROM products WHERE name LIKE ? OR tpnc LIKE ? LIMIT 20", (search, search))
    rows = cur.fetchall()
    conn.close()
    return rows
