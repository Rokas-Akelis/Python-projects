import pandas as pd
import pytest

import bootstrap
import models


def _make_session(tmp_path):
    db_path = tmp_path / "test.db"
    return models.get_session(db_path=f"sqlite:///{db_path}")


def test_merge_wc_csv_updates_and_creates(tmp_path, monkeypatch):
    session = _make_session(tmp_path)
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

    monkeypatch.setattr(bootstrap, "get_session", lambda: session)
    monkeypatch.setattr(bootstrap, "create_backup", lambda label="": None)

    result = bootstrap.merge_wc_csv(csv_path=csv_path)

    assert result == {"new": 1, "updated": 1}
    updated = session.query(models.Product).filter(models.Product.wc_id == 1).one()
    assert updated.price == 11.0
    assert updated.quantity == 7
    assert updated.active is True

    created = session.query(models.Product).filter(models.Product.wc_id == 2).one()
    assert created.name == "Test B"
    assert created.quantity == 0
    assert created.active is False

    raw = session.query(models.WcProductRaw).filter(models.WcProductRaw.wc_id == 1).one()
    assert raw.raw["Pavadinimas"] == "Test A"

    moves = session.query(models.Movement).all()
    assert len(moves) == 1
    assert moves[0].change == 2


def test_merge_wc_csv_sets_wc_id_on_name_match(tmp_path, monkeypatch):
    session = _make_session(tmp_path)
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

    monkeypatch.setattr(bootstrap, "get_session", lambda: session)
    monkeypatch.setattr(bootstrap, "create_backup", lambda label="": None)

    bootstrap.merge_wc_csv(csv_path=csv_path)

    updated = session.query(models.Product).filter(models.Product.id == product.id).one()
    assert updated.wc_id == 3
    assert updated.quantity == 9
    assert session.query(models.Movement).count() == 0


def test_merge_wc_csv_missing_required_columns(tmp_path, monkeypatch):
    session = _make_session(tmp_path)
    df = pd.DataFrame([{"Pavadinimas": "Only name"}])
    csv_path = tmp_path / "wc_missing_cols.csv"
    df.to_csv(csv_path, index=False)

    monkeypatch.setattr(bootstrap, "get_session", lambda: session)
    monkeypatch.setattr(bootstrap, "create_backup", lambda label="": None)

    with pytest.raises(ValueError):
        bootstrap.merge_wc_csv(csv_path=csv_path)


def test_bootstrap_helpers():
    assert bootstrap.normalize_name("  Foo   Bar ") == "foo bar"
    assert bootstrap.to_int("3.0", default=None) == 3
    assert bootstrap.to_int(None, default=7) == 7
    assert bootstrap.to_float("2.5") == 2.5

    row = pd.Series({"A": 1, "B": None, "C": float("nan")})
    cleaned = bootstrap.clean_row_dict(row)
    assert cleaned["A"] == 1
    assert cleaned["B"] is None
    assert cleaned["C"] is None


def test_load_wc_csv_df_from_bytes():
    csv_bytes = b"ID,Pavadinimas\n1,Test\n"
    df = bootstrap._load_wc_csv_df(csv_bytes=csv_bytes)
    assert df.loc[0, "ID"] == 1
