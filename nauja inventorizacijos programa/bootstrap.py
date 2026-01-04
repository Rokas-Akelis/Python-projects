# bootstrap_import.py
import os
import pandas as pd
from pathlib import Path
from models import get_session, Product, Movement, WcProductRaw
from backup_utils import create_backup

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
# WC CSV kelias (naudosim ji demo importui)
WC_CSV_PATH = DATA_DIR / "wc-product-export-16-11-2025-1763321789168.csv"


def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    return " ".join(name.strip().lower().split())


def to_int(val, default=None):
    try:
        if pd.isna(val):
            return default
        return int(float(val))
    except Exception:
        return default


def to_float(val):
    try:
        return float(val) if pd.notna(val) else None
    except Exception:
        return None


def clean_row_dict(row: pd.Series) -> dict:
    """Paverciam i paprasta dict be NaN, kad tilptu i JSON."""
    out = {}
    for k, v in row.items():
        if pd.isna(v):
            out[k] = None
        else:
            out[k] = v
    return out


def sync_wc_csv_merge():
    """
    Nedestruktyvus importas: perskaitome WC CSV ir atnaujiname esamus produktus arba pridedame naujus.
    - Niekas neištrinamas.
    - Tušti laukai CSV paliekami tušti (nenukirsčia esamų reikšmių, jei CSV tuščia).
    - Visi stulpeliai saugomi wc_raw_products.raw.
    """
    # atsargine kopija pries keitimus
    create_backup(label="before_csv_merge")

    session = get_session()

    wc_df = pd.read_csv(WC_CSV_PATH)
    name_col = "Pavadinimas"
    wc_df["norm_name"] = wc_df[name_col].apply(normalize_name)

    # Map esamu produktu pagal wc_id ir norm_name
    products = session.query(Product).all()
    by_wc_id = {p.wc_id: p for p in products if p.wc_id}
    by_norm_name = {normalize_name(p.name): p for p in products if p.name}

    total_upd = 0
    total_new = 0
    for _, row in wc_df.iterrows():
        name = row.get(name_col)
        if not isinstance(name, str) or not name.strip():
            continue
        norm = normalize_name(name)

        wc_id = to_int(row.get("ID"), default=None)
        sku = row.get("Prekes kodas") or row.get("Prekės kodas")
        price = to_float(row.get("Reguliari kaina"))
        quantity = to_int(row.get("Atsargos"), default=None)

        published = str(row.get("Paskelbtas", "")).strip().lower()
        active = published in {"1", "true", "yes", "taip", "published", "publish"}

        product = None
        if wc_id and wc_id in by_wc_id:
            product = by_wc_id[wc_id]
        elif norm and norm in by_norm_name:
            product = by_norm_name[norm]

        if not product:
            product = Product(
                name=name.strip(),
                sku=sku if isinstance(sku, str) and sku.strip() else None,
                wc_id=wc_id,
                cost=None,
                price=price,
                quantity=quantity if quantity is not None else 0,
                active=active,
            )
            session.add(product)
            total_new += 1
        else:
            # atnaujinam laukai tik jei CSV turi reikšmę
            if isinstance(name, str) and name.strip():
                product.name = name.strip()
            if sku and isinstance(sku, str) and sku.strip():
                product.sku = sku.strip()
            if price is not None:
                product.price = price
            if quantity is not None:
                old_qty = product.quantity or 0
                if quantity != old_qty:
                    session.add(Movement(
                        product_id=product.id,
                        change=quantity - old_qty,
                        source="csv_merge",
                        note="Atnaujinta is WC CSV",
                    ))
                product.quantity = quantity
            product.active = active
            total_upd += 1

        # upsert raw
        if wc_id:
            raw_obj = session.query(WcProductRaw).filter(WcProductRaw.wc_id == wc_id).one_or_none()
            payload = clean_row_dict(row)
            if raw_obj:
                raw_obj.raw = payload
            else:
                session.add(WcProductRaw(wc_id=wc_id, raw=payload))

    session.commit()
    print(f"OK. CSV sujungtas. Nauju: {total_new}, atnaujinta: {total_upd}")


if __name__ == "__main__":
    sync_wc_csv_merge()
