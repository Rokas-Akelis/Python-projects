import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import path_setup  # noqa: F401

import sync_to_wc
import models


def _make_session(tmp_path: Path):
    db_path = tmp_path / "test.db"
    return models.get_session(db_path=f"sqlite:///{db_path}")


def _close_session(session):
    try:
        session.close()
    finally:
        bind = getattr(session, "bind", None)
        if bind is not None:
            bind.dispose()


class TestSyncToWC(unittest.TestCase):
    def test_sync_prices_and_stock_filters_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            session = _make_session(tmp_path)
            try:
                session.add(models.WcProductRaw(wc_id=1, raw={"name": "P1"}))
                session.add(models.WcProductRaw(wc_id=2, raw={"name": "P2"}))
                session.add(
                    models.WcProductEdit(
                        wc_id=1,
                        edits={"regular_price": 10.0, "stock_quantity": 5, "manage_stock": True},
                    )
                )
                session.add(
                    models.WcProductEdit(
                        wc_id=2,
                        edits={"regular_price": 20.0},
                    )
                )
                session.commit()

                updates = []

                class FakeWoo:
                    def __init__(self, base_url, consumer_key, consumer_secret):
                        pass

                    def update_products_batch(self, payload):
                        updates.extend(payload)
                        return {"update": [{"id": item.get("id")} for item in payload]}

                with patch.object(sync_to_wc, "WooClient", FakeWoo), patch.object(
                    sync_to_wc, "get_session", return_value=session
                ), patch.object(sync_to_wc, "WC_BASE_URL", "https://example.com"), patch.object(
                    sync_to_wc, "WC_CK", "ck"
                ), patch.object(
                    sync_to_wc, "WC_CS", "cs"
                ):
                    sync_to_wc.sync_prices_and_stock_to_wc(allowed_wc_ids="1")

                self.assertEqual(
                    updates,
                    [
                        {
                            "id": 1,
                            "regular_price": "10.0",
                            "stock_quantity": 5,
                            "manage_stock": True,
                        }
                    ],
                )
            finally:
                _close_session(session)

    def test_pull_products_from_wc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            session = _make_session(tmp_path)
            try:
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

                with patch.object(sync_to_wc, "WooClient", FakeWoo), patch.object(
                    sync_to_wc, "get_session", return_value=session
                ), patch.object(sync_to_wc, "create_backup", lambda label="": None), patch.object(
                    sync_to_wc, "WC_BASE_URL", "https://example.com"
                ), patch.object(
                    sync_to_wc, "WC_CK", "ck"
                ), patch.object(
                    sync_to_wc, "WC_CS", "cs"
                ):
                    sync_to_wc.pull_products_from_wc()

                updated = session.query(models.Product).filter(models.Product.wc_id == 10).one()
                self.assertEqual(updated.price, 2.0)
                self.assertEqual(updated.quantity, 3)
                self.assertEqual(updated.sku, "SKU10")

                created = session.query(models.Product).filter(models.Product.wc_id == 11).one()
                self.assertEqual(created.name, "New")
                self.assertEqual(created.quantity, 0)

                raw = session.query(models.WcProductRaw).filter(models.WcProductRaw.wc_id == 11).one()
                self.assertEqual(raw.raw["name"], "New")

                moves = session.query(models.Movement).filter(
                    models.Movement.product_id == existing.id
                ).all()
                self.assertEqual(len(moves), 1)
                self.assertEqual(moves[0].change, 2)
            finally:
                _close_session(session)

    def test_sync_id_parsing(self):
        self.assertEqual(sync_to_wc._normalize_wc_sync_ids("1, 2;3"), {1, 2, 3})
        self.assertEqual(sync_to_wc._normalize_wc_sync_ids(["4", 5]), {4, 5})
        self.assertEqual(sync_to_wc._normalize_wc_sync_ids(""), set())

        self.assertTrue(sync_to_wc._wc_id_allowed(5, {5, 6}))
        self.assertFalse(sync_to_wc._wc_id_allowed(7, {5, 6}))
