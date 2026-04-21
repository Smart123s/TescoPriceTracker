from datetime import datetime
from unittest.mock import patch, MagicMock
import database_manager as db


TPNC = "12345678"
TODAY = datetime.now().strftime("%Y-%m-%d")

NORMAL_FIELDS = {"price": 249.0, "unit_price": 0.5, "unit_measure": "g"}
DISCOUNT_FIELDS = {
    "price": 199.0, "unit_price": 0.4, "unit_measure": "g",
    "promo_id": "promo1", "promo_desc": "20% OFF",
    "promo_start": TODAY, "promo_end": TODAY,
}


def _make_doc(history=None):
    return {"_id": TPNC, "tpnc": TPNC, "name": "Test Product",
            "price_history": history if history is not None else []}


# ---------------------------------------------------------------------------
# insert_daily_prices
# ---------------------------------------------------------------------------

def test_insert_creates_new_day_entry():
    saved = {}

    def fake_load(_):
        return None

    def fake_save(_, data):
        saved.update(data)

    with patch.object(db, "load_product_data", side_effect=fake_load), \
         patch.object(db, "save_product_data", side_effect=fake_save):

        results = db.insert_daily_prices(TPNC, [("normal", NORMAL_FIELDS)])

    assert results["normal"] is True
    history = saved["price_history"]
    assert len(history) == 1
    assert history[0]["date"] == TODAY
    assert history[0]["normal"] == NORMAL_FIELDS
    assert history[0]["discount"] is None
    assert history[0]["clubcard"] is None


def test_insert_overwrites_same_day():
    existing_doc = _make_doc([{
        "date": TODAY,
        "normal": {"price": 300.0, "unit_price": 0.6, "unit_measure": "g"},
        "discount": None,
        "clubcard": None,
    }])
    saved = {}

    with patch.object(db, "load_product_data", return_value=existing_doc), \
         patch.object(db, "save_product_data", side_effect=lambda _, d: saved.update(d)):

        results = db.insert_daily_prices(TPNC, [("normal", NORMAL_FIELDS)])

    assert results["normal"] is False
    history = saved["price_history"]
    assert len(history) == 1
    assert history[0]["normal"]["price"] == 249.0


def test_insert_multiple_categories_same_day():
    saved = {}

    with patch.object(db, "load_product_data", return_value=None), \
         patch.object(db, "save_product_data", side_effect=lambda _, d: saved.update(d)):

        db.insert_daily_prices(TPNC, [
            ("normal", NORMAL_FIELDS),
            ("discount", DISCOUNT_FIELDS),
        ])

    entry = saved["price_history"][0]
    assert entry["normal"] == NORMAL_FIELDS
    assert entry["discount"] == DISCOUNT_FIELDS
    assert entry["clubcard"] is None


def test_insert_appends_new_day_to_existing_history():
    existing_doc = _make_doc([{
        "date": "2026-04-20",
        "normal": {"price": 300.0, "unit_price": 0.6, "unit_measure": "g"},
        "discount": None,
        "clubcard": None,
    }])
    saved = {}

    with patch.object(db, "load_product_data", return_value=existing_doc), \
         patch.object(db, "save_product_data", side_effect=lambda _, d: saved.update(d)):

        db.insert_daily_prices(TPNC, [("normal", NORMAL_FIELDS)])

    history = saved["price_history"]
    assert len(history) == 2
    assert history[0]["date"] == "2026-04-20"
    assert history[1]["date"] == TODAY


# ---------------------------------------------------------------------------
# get_price_history
# ---------------------------------------------------------------------------

def test_get_price_history_newest_first():
    doc = _make_doc([
        {"date": "2026-04-19", "normal": {"price": 100}, "discount": None, "clubcard": None},
        {"date": "2026-04-20", "normal": {"price": 110}, "discount": None, "clubcard": None},
        {"date": "2026-04-21", "normal": {"price": 120}, "discount": None, "clubcard": None},
    ])

    with patch.object(db, "load_product_data", return_value=doc):
        history = db.get_price_history(TPNC)

    assert history[0]["date"] == "2026-04-21"
    assert history[-1]["date"] == "2026-04-19"


def test_get_price_history_missing_product():
    with patch.object(db, "load_product_data", return_value=None):
        assert db.get_price_history(TPNC) == []


# ---------------------------------------------------------------------------
# get_product_stats
# ---------------------------------------------------------------------------

def test_get_product_stats_basic():
    doc = _make_doc([
        {"date": "2026-04-19", "normal": {"price": 100.0, "unit_price": 1.0, "unit_measure": "g"}, "discount": None, "clubcard": None},
        {"date": "2026-04-20", "normal": {"price": 200.0, "unit_price": 2.0, "unit_measure": "g"}, "discount": None, "clubcard": None},
        {"date": "2026-04-21", "normal": {"price": 150.0, "unit_price": 1.5, "unit_measure": "g"}, "discount": None, "clubcard": None},
    ])
    doc["name"] = "Test"

    with patch.object(db, "load_product_data", return_value=doc):
        stats = db.get_product_stats(TPNC)

    assert stats is not None
    assert stats["total_days"] == 3
    assert stats["first_date"] == "2026-04-19"
    assert stats["last_date"] == "2026-04-21"
    normal = stats["normal"]
    assert normal is not None
    assert normal["min_price"] == 100.0
    assert normal["max_price"] == 200.0
    assert normal["avg_price"] == 150.0
    assert normal["current_price"] == 150.0


def test_get_product_stats_no_discount():
    doc = _make_doc([
        {"date": "2026-04-21", "normal": {"price": 100.0, "unit_price": 1.0, "unit_measure": "g"}, "discount": None, "clubcard": None},
    ])
    doc["name"] = "Test"

    with patch.object(db, "load_product_data", return_value=doc):
        stats = db.get_product_stats(TPNC)

    assert stats is not None
    assert stats["discount"] is None
    assert stats["clubcard"] is None


def test_get_product_stats_not_found():
    with patch.object(db, "load_product_data", return_value=None):
        assert db.get_product_stats(TPNC) is None


# ---------------------------------------------------------------------------
# get_all_product_ids
# ---------------------------------------------------------------------------

def test_get_all_product_ids_pagination():
    mock_coll = MagicMock()
    mock_coll.count_documents.return_value = 3
    mock_cursor = MagicMock()
    mock_cursor.__iter__ = MagicMock(return_value=iter([
        {"_id": "1"}, {"_id": "2"},
    ]))
    mock_coll.find.return_value.skip.return_value.limit.return_value = mock_cursor

    with patch.object(db, "get_db", return_value=mock_coll):
        result = db.get_all_product_ids(skip=0, limit=2)

    assert result["total"] == 3
    assert result["ids"] == ["1", "2"]
    assert result["skip"] == 0
    assert result["limit"] == 2
