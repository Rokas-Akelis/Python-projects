import models
import movement_utils


def _make_session(tmp_path):
    db_path = tmp_path / "test.db"
    return models.get_session(db_path=f"sqlite:///{db_path}")


def test_record_movement(tmp_path):
    session = _make_session(tmp_path)
    product = models.Product(name="Test", wc_id=1, sku="S1", price=1.0, quantity=5, active=True)
    session.add(product)
    session.commit()

    movement_utils.record_movement(session, product, change=3, source="test", note="n1")
    session.commit()

    updated = session.query(models.Product).filter(models.Product.id == product.id).one()
    assert updated.quantity == 8

    moves = session.query(models.Movement).all()
    assert len(moves) == 1
    assert moves[0].change == 3


def test_record_movement_no_change(tmp_path):
    session = _make_session(tmp_path)
    product = models.Product(name="Test", wc_id=1, sku="S1", price=1.0, quantity=5, active=True)
    session.add(product)
    session.commit()

    movement_utils.record_movement(session, product, change=0, source="test", note="n1")
    session.commit()

    moves = session.query(models.Movement).all()
    assert moves == []
