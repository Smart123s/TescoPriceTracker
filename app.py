import os
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import database_manager as db
import stats_manager
import uvicorn

app = FastAPI(title="Tesco Price Tracker API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    db.init_db()

@app.get("/health")
def health_check():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Cache helper
# ---------------------------------------------------------------------------

def _get_stat(key: str, compute_fn, *args):
    """Read from stats_cache; compute on-demand and store if missing."""
    data = db.get_cached_stat(key)
    if data is None:
        data = compute_fn(*args)
        db.set_cached_stat(key, data)
    return data


# ---------------------------------------------------------------------------
# v1 Product endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/products")
def list_product_ids(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Return a paginated list of all product TPNCs."""
    return db.get_all_product_ids(skip=skip, limit=limit)


@app.get("/api/v1/products/search")
def search_products(q: str = Query(default="", min_length=1)):
    """Full-text / regex search on product names. Returns up to 20 results."""
    results = db.search_products(q)
    cleaned = []
    for prod in results:
        prod.pop("_id", None)
        prod.pop("price_history", None)
        cleaned.append(prod)
    return cleaned


@app.get("/api/v1/products/{tpnc}/trend")
def get_product_trend(tpnc: str):
    """Price trend for a single product — cheap, computed on-demand.

    Returns {tpnc, name, history: [{date, normal, discount, clubcard}]}
    """
    prod = db.get_product(tpnc)
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    history = list(reversed(prod.get("price_history", [])))
    return {
        "tpnc":    tpnc,
        "name":    prod.get("name"),
        "history": history,
    }


@app.get("/api/v1/products/{tpnc}/history")
def get_product_history(tpnc: str):
    """Return full daily price history for a product (newest first)."""
    if not db.product_exists(tpnc):
        raise HTTPException(status_code=404, detail="Product not found")
    return db.get_price_history(tpnc)


@app.get("/api/v1/products/{tpnc}/stats")
def get_product_stats(tpnc: str):
    """Return min/max/avg/current price statistics per price category."""
    stats = db.get_product_stats(tpnc)
    if not stats:
        raise HTTPException(status_code=404, detail="Product not found")
    return stats


@app.get("/api/v1/products/{tpnc}")
def get_product(tpnc: str):
    """Return full product document (without price_history)."""
    prod = db.get_product(tpnc)
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    prod.pop("_id", None)
    prod.pop("price_history", None)
    return prod


# ---------------------------------------------------------------------------
# v1 Platform-wide statistics (served from stats_cache)
# ---------------------------------------------------------------------------

@app.get("/api/v1/stats/price-index")
def stats_price_index():
    """Daily platform price index normalized to 100 at the earliest tracked date."""
    return _get_stat("price_index", stats_manager.compute_price_index)


@app.get("/api/v1/stats/product-volume")
def stats_product_volume():
    """Total, active today, and historical-only product counts."""
    return _get_stat("product_counts", stats_manager.compute_product_counts)


@app.get("/api/v1/stats/price-tiers")
def stats_price_tiers():
    """Count of products in each price tier based on latest normal price."""
    return _get_stat("price_tiers", stats_manager.compute_price_tiers)


@app.get("/api/v1/stats/category-diff")
def stats_category_diff():
    """Avg normal / discount / clubcard prices and % differences."""
    return _get_stat("category_diff", stats_manager.compute_category_diff)


@app.get("/api/v1/stats/top-discounts")
def stats_top_discounts(date: str = Query(default=None)):
    """All discounted products on a given date, grouped by % off (desc).

    Defaults to today. Pass ?date=YYYY-MM-DD for a historical date.
    Historical dates are computed on-demand (not pre-cached).
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    cache_key = f"top_discounts_{date}"
    return _get_stat(cache_key, stats_manager.compute_top_discounts, date)


@app.get("/api/v1/stats/best-shopping-day")
def stats_best_shopping_day():
    """The single date historically with the highest total discount savings."""
    return _get_stat("best_shopping_day", stats_manager.compute_best_shopping_day)


@app.get("/api/v1/stats/discount-by-weekday")
def stats_discount_by_weekday():
    """Average discount % and event count per weekday (Mon–Sun)."""
    return _get_stat("discount_by_weekday", stats_manager.compute_discount_by_weekday)


@app.get("/api/v1/stats/volatility")
def stats_volatility():
    """Price volatility index per price tier (std-dev of last 30 days)."""
    return _get_stat("volatility_index", stats_manager.compute_volatility_index)


@app.get("/api/v1/stats/global-avg")
def stats_global_avg():
    """Mean of all products' latest normal price."""
    return _get_stat("global_avg", stats_manager.compute_global_avg)


@app.get("/api/v1/stats/inflation/30d")
def stats_inflation_30d():
    """% change in platform avg price between today and 30 days ago."""
    return _get_stat("inflation_30d", stats_manager.compute_inflation_30d)


@app.get("/api/v1/stats/price-drops/today")
def stats_price_drops_today():
    """Products whose normal price dropped today vs yesterday, sorted by drop %."""
    return _get_stat("price_drops_today", stats_manager.compute_price_drops_today)


# ---------------------------------------------------------------------------
# Legacy shim (browser extension compatibility)
# ---------------------------------------------------------------------------

@app.get("/{tpnc}.json")
def get_legacy_product_json(tpnc: str):
    """Compatibility shim for the existing browser extension."""
    prod = db.get_product(tpnc)
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    prod.pop("_id", None)
    return prod


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("API_PUBLIC_PORT", "50202")),
    )
