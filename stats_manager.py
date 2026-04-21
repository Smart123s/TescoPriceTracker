"""Pre-computes and caches platform-wide statistics into the stats_cache collection.

Intended to be called once at the end of each daily scraper run via rebuild_all_cache().
Each compute_* function can also be called standalone (the API falls back to on-demand
computation when the cache is cold).
"""

import math
import logging
from collections import defaultdict
from datetime import datetime, timedelta

import database_manager as db

logger = logging.getLogger(__name__)

# Price tier boundaries (in HUF)
PRICE_TIERS = [
    (0,       1_000,   "0–1 000"),
    (1_000,   5_000,   "1 000–5 000"),
    (5_000,   10_000,  "5 000–10 000"),
    (10_000,  20_000,  "10 000–20 000"),
    (20_000,  50_000,  "20 000–50 000"),
    (50_000,  100_000, "50 000–100 000"),
    (100_000, None,    "100 000+"),
]

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _iter_all_products(projection=None):
    """Stream all product documents from MongoDB without loading all into memory."""
    coll = db.get_db()
    assert coll is not None
    proj = projection or {}
    return coll.find({}, proj, batch_size=500)


def _tier_label(price):
    for lo, hi, label in PRICE_TIERS:
        if hi is None or price < hi:
            if price >= lo:
                return label
    return PRICE_TIERS[-1][2]


def _stddev(values):
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _latest_entry(history):
    """Return the most recent daily entry from a price_history list, or None."""
    if not history or isinstance(history, dict):
        return None
    # History is stored oldest-first; last element is newest
    return history[-1]


def _entry_for_date(history, date_str):
    if isinstance(history, dict):
        return None
    for entry in history:
        if isinstance(entry, dict) and entry.get("date") == date_str:
            return entry
    return None


# ---------------------------------------------------------------------------
# Compute functions
# ---------------------------------------------------------------------------

def compute_price_index():
    """Daily avg normal price across all products, normalized to index=100 at earliest date.

    Returns list of {date, index} sorted ascending by date.
    """
    date_sums: dict[str, list] = defaultdict(list)

    for doc in _iter_all_products({"price_history": 1}):
        for entry in doc.get("price_history", []):
            normal = entry.get("normal")
            if normal and normal.get("price") is not None:
                date_sums[entry["date"]].append(normal["price"])

    if not date_sums:
        return []

    sorted_dates = sorted(date_sums)
    first_avg = sum(date_sums[sorted_dates[0]]) / len(date_sums[sorted_dates[0]])
    if first_avg == 0:
        return []

    result = []
    for date in sorted_dates:
        avg = sum(date_sums[date]) / len(date_sums[date])
        result.append({"date": date, "index": round(avg / first_avg * 100, 2)})

    return result


def compute_product_counts():
    """Return total, active_today (scraped today), and historical_only counts."""
    coll = db.get_db()
    assert coll is not None

    today_start = datetime.now().strftime("%Y-%m-%d")
    total = coll.count_documents({})
    active_today = coll.count_documents(
        {"last_scraped_price": {"$gte": today_start}}
    )
    return {
        "total": total,
        "active_today": active_today,
        "historical_only": total - active_today,
    }


def compute_price_tiers():
    """Count of products per price tier based on their latest normal price."""
    tier_counts: dict[str, int] = {label: 0 for _, _, label in PRICE_TIERS}

    for doc in _iter_all_products({"price_history": 1}):
        entry = _latest_entry(doc.get("price_history", []))
        if not entry:
            continue
        normal = entry.get("normal")
        if not normal or normal.get("price") is None:
            continue
        label = _tier_label(normal["price"])
        tier_counts[label] = tier_counts.get(label, 0) + 1

    return [{"tier": label, "count": tier_counts[label]} for _, _, label in PRICE_TIERS]


def compute_category_diff():
    """Avg normal / discount / clubcard price across all products (latest day).

    Returns avg values and % differences vs normal.
    """
    normals, discounts, clubcards = [], [], []

    for doc in _iter_all_products({"price_history": 1}):
        entry = _latest_entry(doc.get("price_history", []))
        if not entry:
            continue
        n = entry.get("normal")
        d = entry.get("discount")
        c = entry.get("clubcard")
        if n and n.get("price") is not None:
            normals.append(n["price"])
        if d and d.get("price") is not None:
            discounts.append(d["price"])
        if c and c.get("price") is not None:
            clubcards.append(c["price"])

    avg_normal   = round(sum(normals)   / len(normals),   2) if normals   else None
    avg_discount = round(sum(discounts) / len(discounts), 2) if discounts else None
    avg_clubcard = round(sum(clubcards) / len(clubcards), 2) if clubcards else None

    def pct_diff(base, other):
        if base and other:
            return round((other - base) / base * 100, 2)
        return None

    return {
        "avg_normal":   avg_normal,
        "avg_discount": avg_discount,
        "avg_clubcard": avg_clubcard,
        "discount_vs_normal_pct": pct_diff(avg_normal, avg_discount),
        "clubcard_vs_normal_pct": pct_diff(avg_normal, avg_clubcard),
        "products_with_discount": len(discounts),
        "products_with_clubcard": len(clubcards),
    }


def compute_top_discounts(date_str=None):
    """All discounted products on date_str, grouped by % off (desc).

    Returns [{pct_off, products: [{tpnc, name, normal_price, discount_price, promo_desc}]}]
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    buckets: dict[float, list] = defaultdict(list)

    for doc in _iter_all_products({"_id": 1, "name": 1, "price_history": 1}):
        entry = _entry_for_date(doc.get("price_history", []), date_str)
        if not entry:
            continue
        normal = entry.get("normal")
        discount = entry.get("discount")
        if not normal or not discount:
            continue
        np_ = normal.get("price")
        dp_ = discount.get("price")
        if np_ is None or dp_ is None or np_ == 0:
            continue
        pct_off = round((np_ - dp_) / np_ * 100, 1)
        if pct_off <= 0:
            continue
        buckets[pct_off].append({
            "tpnc":          str(doc["_id"]),
            "name":          doc.get("name"),
            "normal_price":  np_,
            "discount_price": dp_,
            "promo_desc":    discount.get("promo_desc"),
        })

    return [
        {"pct_off": pct, "products": buckets[pct]}
        for pct in sorted(buckets, reverse=True)
    ]


def compute_best_shopping_day():
    """Return the date with the highest total savings (sum of normal-discount) historically."""
    date_savings: dict[str, float] = defaultdict(float)

    for doc in _iter_all_products({"price_history": 1}):
        for entry in doc.get("price_history", []):
            normal = entry.get("normal")
            discount = entry.get("discount")
            if not normal or not discount:
                continue
            np_ = normal.get("price")
            dp_ = discount.get("price")
            if np_ is not None and dp_ is not None:
                date_savings[entry["date"]] += (np_ - dp_)

    if not date_savings:
        return {"date": None, "total_savings": None}

    best = max(date_savings, key=lambda d: date_savings[d])
    return {"date": best, "total_savings": round(date_savings[best], 2)}


def compute_discount_by_weekday():
    """Avg discount % and event count per weekday (Mon–Sun) across all history."""
    weekday_pcts: dict[int, list] = defaultdict(list)

    for doc in _iter_all_products({"price_history": 1}):
        for entry in doc.get("price_history", []):
            normal = entry.get("normal")
            discount = entry.get("discount")
            if not normal or not discount:
                continue
            np_ = normal.get("price")
            dp_ = discount.get("price")
            if np_ is None or dp_ is None or np_ == 0:
                continue
            pct_off = (np_ - dp_) / np_ * 100
            if pct_off <= 0:
                continue
            try:
                wd = datetime.strptime(entry["date"], "%Y-%m-%d").weekday()
                weekday_pcts[wd].append(pct_off)
            except (ValueError, KeyError):
                continue

    result = []
    for wd in range(7):
        pcts = weekday_pcts[wd]
        result.append({
            "weekday":      WEEKDAY_NAMES[wd],
            "avg_pct_off":  round(sum(pcts) / len(pcts), 2) if pcts else 0.0,
            "total_events": len(pcts),
        })
    return result


def compute_volatility_index():
    """Per price tier: avg std-dev of normal price over last 30 days."""
    today = datetime.now().date()
    cutoff = (today - timedelta(days=30)).isoformat()

    tier_vols: dict[str, list] = defaultdict(list)

    for doc in _iter_all_products({"price_history": 1}):
        history = doc.get("price_history", [])
        recent_prices = [
            e["normal"]["price"]
            for e in history
            if e.get("date", "") >= cutoff
            and e.get("normal")
            and e["normal"].get("price") is not None
        ]
        if len(recent_prices) < 2:
            continue
        latest_entry = _latest_entry(history)
        if not latest_entry or not latest_entry.get("normal"):
            continue
        latest_price = latest_entry["normal"].get("price")
        if latest_price is None:
            continue
        label = _tier_label(latest_price)
        tier_vols[label].append(_stddev(recent_prices))

    result = []
    for _, _, label in PRICE_TIERS:
        vols = tier_vols[label]
        result.append({
            "tier":           label,
            "avg_volatility": round(sum(vols) / len(vols), 4) if vols else 0.0,
            "product_count":  len(vols),
        })
    return result


def compute_global_avg():
    """Mean of all products' latest normal price."""
    prices = []
    for doc in _iter_all_products({"price_history": 1}):
        entry = _latest_entry(doc.get("price_history", []))
        if not entry:
            continue
        normal = entry.get("normal")
        if normal and normal.get("price") is not None:
            prices.append(normal["price"])

    return {
        "avg_price":     round(sum(prices) / len(prices), 2) if prices else None,
        "product_count": len(prices),
    }


def compute_inflation_30d():
    """% change between today's global avg price and 30 days ago."""
    today = datetime.now().strftime("%Y-%m-%d")
    thirty_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    today_prices, old_prices = [], []

    for doc in _iter_all_products({"price_history": 1}):
        history = doc.get("price_history", [])
        today_entry = _entry_for_date(history, today)
        old_entry   = _entry_for_date(history, thirty_ago)

        n_today = today_entry.get("normal") if today_entry else None
        n_old   = old_entry.get("normal")   if old_entry   else None

        if n_today and n_today.get("price") is not None:
            today_prices.append(n_today["price"])
        if n_old and n_old.get("price") is not None:
            old_prices.append(n_old["price"])

    avg_today  = sum(today_prices) / len(today_prices) if today_prices else None
    avg_30d_ago = sum(old_prices)  / len(old_prices)   if old_prices   else None

    if avg_today and avg_30d_ago and avg_30d_ago != 0:
        pct_change = round((avg_today - avg_30d_ago) / avg_30d_ago * 100, 2)
    else:
        pct_change = None

    return {
        "pct_change":  pct_change,
        "avg_today":   round(avg_today, 2)   if avg_today   else None,
        "avg_30d_ago": round(avg_30d_ago, 2) if avg_30d_ago else None,
        "date_today":  today,
        "date_30d_ago": thirty_ago,
    }


def compute_price_drops_today():
    """Products where today's normal price is lower than yesterday's."""
    today     = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    drops = []
    for doc in _iter_all_products({"_id": 1, "name": 1, "price_history": 1}):
        history = doc.get("price_history", [])
        today_entry     = _entry_for_date(history, today)
        yesterday_entry = _entry_for_date(history, yesterday)
        if not today_entry or not yesterday_entry:
            continue

        n_today = today_entry.get("normal")
        n_yest  = yesterday_entry.get("normal")
        if not n_today or not n_yest:
            continue

        p_today = n_today.get("price")
        p_yest  = n_yest.get("price")
        if p_today is None or p_yest is None or p_today >= p_yest:
            continue

        drops.append({
            "tpnc":            str(doc["_id"]),
            "name":            doc.get("name"),
            "yesterday_price": p_yest,
            "today_price":     p_today,
            "drop_amount":     round(p_yest - p_today, 2),
            "drop_pct":        round((p_yest - p_today) / p_yest * 100, 2),
        })

    drops.sort(key=lambda x: x["drop_pct"], reverse=True)
    return drops


# ---------------------------------------------------------------------------
# Cache orchestrator
# ---------------------------------------------------------------------------

def rebuild_all_cache():
    """Compute all platform-wide stats and write them to the stats_cache collection.

    Called automatically at the end of each successful daily scrape.
    Safe to call manually: python -c "import stats_manager; stats_manager.rebuild_all_cache()"
    """
    today = datetime.now().strftime("%Y-%m-%d")

    tasks = [
        ("price_index",       compute_price_index),
        ("product_counts",    compute_product_counts),
        ("price_tiers",       compute_price_tiers),
        ("category_diff",     compute_category_diff),
        (f"top_discounts_{today}", lambda: compute_top_discounts(today)),
        ("best_shopping_day", compute_best_shopping_day),
        ("discount_by_weekday", compute_discount_by_weekday),
        ("volatility_index",  compute_volatility_index),
        ("global_avg",        compute_global_avg),
        ("inflation_30d",     compute_inflation_30d),
        ("price_drops_today", compute_price_drops_today),
    ]

    for key, fn in tasks:
        try:
            logger.info(f"Computing stat: {key}")
            data = fn()
            db.set_cached_stat(key, data)
            logger.info(f"Cached stat: {key}")
        except Exception as e:
            logger.error(f"Failed to compute stat {key}: {e}")

    logger.info("Stats cache rebuild complete.")
