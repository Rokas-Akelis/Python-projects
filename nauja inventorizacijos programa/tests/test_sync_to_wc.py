import types

import sync_to_wc
import models


def _make_session(tmp_path):
    db_path = tmp_path / "test.db"
    return models.get_session(db_path=f"sqlite:///{db_path}")


def test_sync_prices_and_stock_filters_ids(tmp_path, monkeypatch):
    session = _make_session(tmp_path)
    session.add(models.Product(name="P1", wc_id=1, price=10.0, quantity=5, active=True))
    session.add(models.Product(name="P2", wc_id=2, price=20.0, quantity=6, active=True))
    session.commit()

    updates = []

    class FakeWoo:
        def __init__(self, base_url, consumer_key, consumer_secret):
            pass

        def get_product(self, wc_id):
            return {"type": "simple", "regular_price": "1.0", "stock_quantity": 1}

        def update_price_and_stock(self, wc_id, price, quantity):
            updates.append((wc_id, price, quantity))
            return {"id": wc_id}

    monkeypatch.setattr(sync_to_wc, "WooClient", FakeWoo)
    monkeypatch.setattr(sync_to_wc, "get_session", lambda: session)
    monkeypatch.setattr(sync_to_wc, "WC_BASE_URL", "https://example.com")
    monkeypatch.setattr(sync_to_wc, "WC_CK", "ck")
    monkeypatch.setattr(sync_to_wc, "WC_CS", "cs")

    sync_to_wc.sync_prices_and_stock_to_wc(allowed_wc_ids="1")

    assert updates == [(1, 10.0, 5)]


def test_pull_products_from_wc(tmp_path, monkeypatch):
    session = _make_session(tmp_path)
    existing = models.Product(name="Old", wc_id=10, price=1.0, quantity=1, active=True)
    session.add(existing)
    session.commit()

    items = [
        {
            "id": 10,
            "name": "Old",
            "regular_price": "2.0",
            "stock_quantity": 3,
            "sku": "SKU10",
        },
        {
            "id": 11,
            "name": "New",
            "regular_price": "4.0",
            "stock_quantity": 0,
            "sku": None,
        },
    ]

    class FakeWoo:
        def __init__(self, base_url, consumer_key, consumer_secret):
            self.page = 0

        def list_products(self, page=1, per_page=100):
            if page == 1:
                return items
            return []

    monkeypatch.setattr(sync_to_wc, "WooClient", FakeWoo)
    monkeypatch.setattr(sync_to_wc, "get_session", lambda: session)
    monkeypatch.setattr(sync_to_wc, "create_backup", lambda label="": None)
    monkeypatch.setattr(sync_to_wc, "WC_BASE_URL", "https://example.com")
    monkeypatch.setattr(sync_to_wc, "WC_CK", "ck")
    monkeypatch.setattr(sync_to_wc, "WC_CS", "cs")

    sync_to_wc.pull_products_from_wc()

    updated = session.query(models.Product).filter(models.Product.wc_id == 10).one()
    assert updated.price == 2.0
    assert updated.quantity == 3
    assert updated.sku == "SKU10"

    created = session.query(models.Product).filter(models.Product.wc_id == 11).one()
    assert created.name == "New"
    assert created.quantity == 0

    raw = session.query(models.WcProductRaw).filter(models.WcProductRaw.wc_id == 11).one()
    assert raw.raw["name"] == "New"

    moves = session.query(models.Movement).filter(models.Movement.product_id == existing.id).all()
    assert len(moves) == 1
    assert moves[0].change == 2


def test_sync_id_parsing():
    assert sync_to_wc._normalize_wc_sync_ids("1, 2;3") == {1, 2, 3}
    assert sync_to_wc._normalize_wc_sync_ids(["4", 5]) == {4, 5}
    assert sync_to_wc._normalize_wc_sync_ids("") == set()

    assert sync_to_wc._wc_id_allowed(5, {5, 6}) is True
    assert sync_to_wc._wc_id_allowed(7, {5, 6}) is False
