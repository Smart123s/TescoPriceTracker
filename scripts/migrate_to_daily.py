"""Migrate price_history from period-folding format to daily snapshots.

Old format:
  price_history: {
    "normal":   [{"price": ..., "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", ...}],
    "discount": [...],
    "clubcard": [...]
  }

New format:
  price_history: [
    {"date": "YYYY-MM-DD", "normal": {...}, "discount": {...}, "clubcard": null},
    ...
  ]

Usage:
  python scripts/migrate_to_daily.py              # live run
  python scripts/migrate_to_daily.py --dry-run    # preview first 5 products, no writes
"""

import argparse
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pymongo import MongoClient, UpdateOne
from config import MONGO_URI, MONGO_DB_NAME, MONGO_COLLECTION

BATCH_SIZE = 500


def date_range(start_str, end_str):
    """Yield ISO date strings for every day in [start_str, end_str]."""
    try:
        start = datetime.strptime(start_str, "%Y-%m-%d").date()
        end = datetime.strptime(end_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return
    current = start
    while current <= end:
        yield current.isoformat()
        current += timedelta(days=1)


def _strip_period_keys(fields):
    """Remove start_date/end_date from a period entry to get pure price fields."""
    return {k: v for k, v in fields.items() if k not in ("start_date", "end_date")}


def convert_product(doc):
    """Convert one product document to the new daily format.

    Returns the new price_history list, or None if already in new format.
    """
    raw_history = doc.get("price_history")

    # Already migrated (list of daily dicts) — skip
    if isinstance(raw_history, list):
        # Check if it's the new format (entries have "date" key but no "start_date")
        if not raw_history or "date" in raw_history[0]:
            return None

    # Old format: dict with category keys
    if not isinstance(raw_history, dict):
        return []

    # Accumulate per-day data: date -> {normal, discount, clubcard}
    daily: dict[str, dict] = {}

    for category in ("normal", "discount", "clubcard"):
        periods = raw_history.get(category, [])
        for period in periods:
            start = period.get("start_date")
            end = period.get("end_date")
            if not start or not end:
                continue
            fields = _strip_period_keys(period)
            for day in date_range(start, end):
                if day not in daily:
                    daily[day] = {"date": day, "normal": None, "discount": None, "clubcard": None}
                daily[day][category] = fields

    # Sort by date ascending (oldest first = storage order)
    return [daily[d] for d in sorted(daily)]


def migrate(dry_run=False):
    client = MongoClient(MONGO_URI)
    collection = client[MONGO_DB_NAME][MONGO_COLLECTION]

    total = collection.count_documents({})
    print(f"Total products: {total}")
    if dry_run:
        print("DRY RUN — no writes will be made. Showing first 5 products.\n")

    processed = 0
    skipped = 0
    converted = 0
    operations = []

    cursor = collection.find({}, {"price_history": 1, "tpnc": 1, "name": 1})

    for doc in cursor:
        new_history = convert_product(doc)
        if new_history is None:
            skipped += 1
            processed += 1
            continue

        if dry_run and converted < 5:
            print(f"  TPNC {doc.get('_id')} ({doc.get('name', '?')[:40]})")
            print(f"    Old keys: {list(doc.get('price_history', {}).keys())}")
            print(f"    New days: {len(new_history)}")
            if new_history:
                print(f"    First day: {new_history[0]}")
            print()

        operations.append(
            UpdateOne({"_id": doc["_id"]}, {"$set": {"price_history": new_history}})
        )
        converted += 1
        processed += 1

        if not dry_run and len(operations) >= BATCH_SIZE:
            collection.bulk_write(operations)
            operations = []
            print(f"  Written {processed}/{total} ...")

    if not dry_run and operations:
        collection.bulk_write(operations)

    print(f"\nDone. Converted: {converted}, Already new format (skipped): {skipped}, Total: {processed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate price_history to daily format")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
