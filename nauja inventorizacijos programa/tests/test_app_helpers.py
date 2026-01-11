import sys
import tempfile
import types
import unittest
from pathlib import Path

import path_setup  # noqa: F401

import models


if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = types.SimpleNamespace()

import app  # noqa: E402


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


class TestAppHelpers(unittest.TestCase):
    def test_app_helpers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            session = _make_session(tmp_path)
            try:
                product = models.Product(
                    name="Test",
                    wc_id=1,
                    sku="SKU1",
                    price=2.5,
                    quantity=3,
                    active=True,
                )
                session.add(product)
                session.commit()

                session.add(models.Movement(product_id=product.id, change=2, source="test", note="n1"))
                session.add(
                    models.WcProductRaw(
                        wc_id=1, raw={"name": "Test", "tags": ["a", "b"], "meta": {"k": "v"}}
                    )
                )
                session.commit()

            products_df = app.load_products_df(session)
            self.assertEqual(products_df.iloc[0]["Pavadinimas"], "Test")
            self.assertEqual(products_df.iloc[0]["Kiekis"], 3)

                moves_df = app.load_movements_df(session)
                self.assertEqual(moves_df.loc[0, "Produktas"], "Test")
                self.assertEqual(moves_df.loc[0, "Kiekio pokytis"], 2)

                raw_df = app.load_wc_raw_df(session)
                self.assertEqual(raw_df.loc[0, "wc_id"], 1)
                self.assertEqual(raw_df.loc[0, "tags"], '["a", "b"]')
                self.assertEqual(raw_df.loc[0, "meta.k"], "v")

                self.assertEqual(app.to_int("5.0"), 5)
                self.assertEqual(app.to_int(None, default=7), 7)
                self.assertEqual(app.to_float("3.5"), 3.5)
            finally:
                _close_session(session)
