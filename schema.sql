-- Products table for static details
CREATE TABLE IF NOT EXISTS products (
    tpnc TEXT PRIMARY KEY,
    name TEXT,
    unit_of_measure TEXT, -- e.g., kg, unit
    default_image_url TEXT,
    pack_size_value TEXT,
    pack_size_unit TEXT,
    last_scraped_static DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_scraped_price DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Price History table
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tpnc TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    price_actual REAL,
    unit_price REAL,
    unit_measure TEXT,
    is_promotion BOOLEAN DEFAULT 0,
    promotion_id TEXT,
    promotion_description TEXT,
    promotion_start DATETIME,
    promotion_end DATETIME,
    clubcard_price REAL,
    FOREIGN KEY(tpnc) REFERENCES products(tpnc)
);
