import sys
import types

import models


if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = types.SimpleNamespace()

import app  # noqa: E402


def _make_session(tmp_path):
    db_path = tmp_path / "test.db"
    return models.get_session(db_path=f"sqlite:///{db_path}")


def test_app_helpers(tmp_path):
    session = _make_session(tmp_path)
    product = models.Product(name="Test", wc_id=1, sku="SKU1", price=2.5, quantity=3, active=True)
    session.add(product)
    session.commit()

    session.add(models.Movement(product_id=product.id, change=2, source="test", note="n1"))
    session.add(models.WcProductRaw(wc_id=1, raw={"name": "Test", "tags": ["a", "b"], "meta": {"k": "v"}}))
    session.commit()

    products_df = app.load_products_df(session)
    assert products_df.loc[0, "Pavadinimas"] == "Test"
    assert products_df.loc[0, "Kiekis"] == 3

    moves_df = app.load_movements_df(session)
    assert moves_df.loc[0, "Produktas"] == "Test"
    assert moves_df.loc[0, "Kiekio pokytis"] == 2

    raw_df = app.load_wc_raw_df(session)
    assert raw_df.loc[0, "wc_id"] == 1
    assert raw_df.loc[0, "tags"] == '["a", "b"]'
    assert raw_df.loc[0, "meta.k"] == "v"

    assert app.to_int("5.0") == 5
    assert app.to_int(None, default=7) == 7
    assert app.to_float("3.5") == 3.5
