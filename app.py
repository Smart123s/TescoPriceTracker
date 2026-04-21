from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import database_manager as db
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
# v1 API
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
    return prod


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
    uvicorn.run("app:app", host="0.0.0.0", port=5000)
