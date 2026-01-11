import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import path_setup  # noqa: F401

import bootstrap
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


class TestBootstrap(unittest.TestCase):
    def test_merge_wc_csv_updates_and_creates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            session = _make_session(tmp_path)
            try:
                existing = models.Product(
                    name="Test A",
                    wc_id=1,
                    sku="SKU1",
                    price=10.0,
                    quantity=5,
                    active=True,
                )
                session.add(existing)
                session.commit()

                df = pd.DataFrame(
                    [
                        {
                            "ID": 1,
                            "Pavadinimas": "Test A",
                            "Prekes kodas": "SKU1",
                            "Reguliari kaina": 11.0,
                            "Atsargos": 7,
                            "Paskelbtas": 1,
                        },
                        {
                            "ID": 2,
                            "Pavadinimas": "Test B",
                            "Prekes kodas": "",
                            "Reguliari kaina": 5.5,
                            "Atsargos": None,
                            "Paskelbtas": 0,
                        },
                    ]
                )
                csv_path = tmp_path / "wc.csv"
                df.to_csv(csv_path, index=False)

                with patch.object(bootstrap, "get_session", return_value=session), patch.object(
                    bootstrap, "create_backup", lambda label="": None
                ):
                    result = bootstrap.merge_wc_csv(csv_path=csv_path)

                self.assertEqual(result, {"new": 1, "updated": 1})
                updated = session.query(models.Product).filter(models.Product.wc_id == 1).one()
                self.assertEqual(updated.price, 11.0)
                self.assertEqual(updated.quantity, 7)
                self.assertTrue(updated.active)

                created = session.query(models.Product).filter(models.Product.wc_id == 2).one()
                self.assertEqual(created.name, "Test B")
                self.assertEqual(created.quantity, 0)
                self.assertFalse(created.active)

                raw = session.query(models.WcProductRaw).filter(models.WcProductRaw.wc_id == 1).one()
                self.assertEqual(raw.raw["Pavadinimas"], "Test A")

                moves = session.query(models.Movement).all()
                self.assertEqual(len(moves), 1)
                self.assertEqual(moves[0].change, 2)
            finally:
                _close_session(session)

    def test_merge_wc_csv_sets_wc_id_on_name_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            session = _make_session(tmp_path)
            try:
                product = models.Product(
                    name="Test C",
                    wc_id=None,
                    sku=None,
                    price=3.0,
                    quantity=9,
                    active=True,
                )
                session.add(product)
                session.commit()

                df = pd.DataFrame(
                    [
                        {
                            "ID": 3,
                            "Pavadinimas": "Test C",
                            "Prekes kodas": "SKU3",
                            "Reguliari kaina": 3.0,
                            "Atsargos": None,
                            "Paskelbtas": 1,
                        }
                    ]
                )
                csv_path = tmp_path / "wc_missing_qty.csv"
                df.to_csv(csv_path, index=False)

                with patch.object(bootstrap, "get_session", return_value=session), patch.object(
                    bootstrap, "create_backup", lambda label="": None
                ):
                    bootstrap.merge_wc_csv(csv_path=csv_path)

                updated = session.query(models.Product).filter(models.Product.id == product.id).one()
                self.assertEqual(updated.wc_id, 3)
                self.assertEqual(updated.quantity, 9)
                self.assertEqual(session.query(models.Movement).count(), 0)
            finally:
                _close_session(session)

    def test_merge_wc_csv_missing_required_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            session = _make_session(tmp_path)
            try:
                df = pd.DataFrame([{"Pavadinimas": "Only name"}])
                csv_path = tmp_path / "wc_missing_cols.csv"
                df.to_csv(csv_path, index=False)

                with patch.object(bootstrap, "get_session", return_value=session), patch.object(
                    bootstrap, "create_backup", lambda label="": None
                ):
                    with self.assertRaises(ValueError):
                        bootstrap.merge_wc_csv(csv_path=csv_path)
            finally:
                _close_session(session)

    def test_bootstrap_helpers(self):
        self.assertEqual(bootstrap.normalize_name("  Foo   Bar "), "foo bar")
        self.assertEqual(bootstrap.to_int("3.0", default=None), 3)
        self.assertEqual(bootstrap.to_int(None, default=7), 7)
        self.assertEqual(bootstrap.to_float("2.5"), 2.5)

        row = pd.Series({"A": 1, "B": None, "C": float("nan")})
        cleaned = bootstrap.clean_row_dict(row)
        self.assertEqual(cleaned["A"], 1)
        self.assertIsNone(cleaned["B"])
        self.assertIsNone(cleaned["C"])

    def test_load_wc_csv_df_from_bytes(self):
        csv_bytes = b"ID,Pavadinimas\n1,Test\n"
        df = bootstrap._load_wc_csv_df(csv_bytes=csv_bytes)
        self.assertEqual(df.loc[0, "ID"], 1)
