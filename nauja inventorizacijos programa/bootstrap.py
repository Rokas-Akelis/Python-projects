# bootstrap_import.py
import pandas as pd
from models import get_session, Product, Movement, WcProductRaw

# WC CSV kelias (naudosim ji demo importui)
WC_CSV_PATH = r"C:\Users\rokas\Desktop\nauja inventorius\wc-product-export-16-11-2025-1763321789168.csv"


def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    return " ".join(name.strip().lower().split())


def to_int(val, default=0):
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


def import_wc_only():
    """
    Demo importas: isvalom lentele ir uzpildom vien WC CSV duomenimis.
    """
    session = get_session()

    # Išvalome senus judėjimus ir produktus, kad nekiltų konfliktų su unique name
    session.query(Movement).delete()
    session.query(Product).delete()
    session.query(WcProductRaw).delete()
    session.commit()

    wc_df = pd.read_csv(WC_CSV_PATH)
    wc_df["norm_name"] = wc_df["Pavadinimas"].apply(normalize_name)

    seen_names = set()
    seen_wc_ids = set()

    for _, row in wc_df.iterrows():
        name = row.get("Pavadinimas")
        if not isinstance(name, str) or not name.strip():
            continue

        wc_id = to_int(row.get("ID"), default=None)
        sku = row.get("Prekės kodas")
        price = to_float(row.get("Reguliari kaina"))
        quantity = to_int(row.get("Atsargos"), default=0)

        published = str(row.get("Paskelbtas", "")).strip().lower()
        active = published in {"1", "true", "yes", "taip", "published", "publish"}

        # vengiam dubliu to paties pavadinimo ar WC ID
        if name.strip() in seen_names or (wc_id and wc_id in seen_wc_ids):
            continue

        # saugom pilna WC eilute i JSON
        raw_payload = clean_row_dict(row)
        session.add(WcProductRaw(wc_id=wc_id, raw=raw_payload))

        product = Product(
            name=name.strip(),
            sku=sku if isinstance(sku, str) and sku.strip() else None,
            wc_id=wc_id,
            cost=None,
            price=price,
            quantity=quantity,
            active=active,
        )
        session.add(product)
        seen_names.add(name.strip())
        if wc_id:
            seen_wc_ids.add(wc_id)

    session.commit()
    print(f"OK. WC importas baigtas. Produktu: {session.query(Product).count()}")


if __name__ == "__main__":
    import_wc_only()
