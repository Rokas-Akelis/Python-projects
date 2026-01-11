import tempfile
import unittest
from pathlib import Path

import path_setup  # noqa: F401

import models
import movement_utils


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


class TestMovementUtils(unittest.TestCase):
    def test_record_movement(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            session = _make_session(tmp_path)
            try:
                product = models.Product(
                    name="Test",
                    wc_id=1,
                    sku="S1",
                    price=1.0,
                    quantity=5,
                    active=True,
                )
                session.add(product)
                session.commit()

                movement_utils.record_movement(session, product, change=3, source="test", note="n1")
                session.commit()

                updated = session.query(models.Product).filter(models.Product.id == product.id).one()
                self.assertEqual(updated.quantity, 8)

                moves = session.query(models.Movement).all()
                self.assertEqual(len(moves), 1)
                self.assertEqual(moves[0].change, 3)
            finally:
                _close_session(session)

    def test_record_movement_no_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            session = _make_session(tmp_path)
            try:
                product = models.Product(
                    name="Test",
                    wc_id=1,
                    sku="S1",
                    price=1.0,
                    quantity=5,
                    active=True,
                )
                session.add(product)
                session.commit()

                movement_utils.record_movement(session, product, change=0, source="test", note="n1")
                session.commit()

                moves = session.query(models.Movement).all()
                self.assertEqual(moves, [])
            finally:
                _close_session(session)
