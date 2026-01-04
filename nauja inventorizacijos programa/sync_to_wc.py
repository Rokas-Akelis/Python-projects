# sync_to_wc.py
import os
from models import get_session, Product, Movement, WcProductRaw
from woo_client import WooClient
from backup_utils import create_backup

DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"
WC_BASE_URL = os.getenv("WC_BASE_URL")
WC_CK = os.getenv("WC_CK")
WC_CS = os.getenv("WC_CS")


def sync_prices_and_stock_to_wc():
    session = get_session()

    woo = None
    if DEMO_MODE:
        print("Demo mode: WooCommerce API calls are skipped.")
    else:
        if not (WC_BASE_URL and WC_CK and WC_CS):
            raise RuntimeError("WC_BASE_URL/WC_CK/WC_CS not set")
        woo = WooClient(base_url=WC_BASE_URL, consumer_key=WC_CK, consumer_secret=WC_CS)

    products = session.query(Product).filter(Product.active == True).all()

    for p in products:
        if not p.wc_id:
            continue

        if DEMO_MODE:
            print(f"Demo mode: would sync WC_ID={p.wc_id} ({p.name})")
            continue

        try:
            current = None
            try:
                current = woo.get_product(p.wc_id)
            except Exception as e_get:
                print(f"WC ID={p.wc_id}: nepavyko perskaityti esamo produkto ({e_get}), bandome vis tiek atnaujinti.")

            wc_type = current.get("type") if isinstance(current, dict) else None
            if wc_type and wc_type not in {"simple"}:
                print(f"WC ID={p.wc_id}: type={wc_type} nepalaikomas (variacija/variable). Šiuo metu neatnaujinama.")
                continue

            current_price = None
            current_qty = None
            if isinstance(current, dict):
                current_price = current.get("regular_price")
                try:
                    current_price = float(current_price) if current_price not in ("", None) else None
                except Exception:
                    current_price = None
                current_qty = current.get("stock_quantity")
                try:
                    current_qty = int(current_qty) if current_qty is not None else None
                except Exception:
                    current_qty = None

            woo.update_price_and_stock(
                wc_id=p.wc_id,
                price=p.price,
                quantity=p.quantity,
            )
            print(
                f"OK. WC_ID={p.wc_id} ({p.name})"
                f" price {current_price}->{p.price}, qty {current_qty}->{p.quantity}"
            )
        except Exception as e:
            # jei 404 - WC pusėje nėra tokio ID, tiesiog praleidžiam nekeičiant DB
            if hasattr(e, "response") and getattr(e.response, "status_code", None) == 404:
                print(f"WC ID={p.wc_id} nerastas (404). Praleidžiama, DB neliečiama: {p.name}")
                continue
            print(f"Klaida WC atnaujinant {p.name}: {e}")


def pull_products_from_wc():
    """
    Persikrauna duomenis is WooCommerce i DB:
    - WC API -> atnaujinanuraria Product
    - Issaugo pilna raw JSON i wc_raw_products
    - Kiekiu pokycius zymi Movement
    """
    if DEMO_MODE:
        raise RuntimeError("Demo mode: WC pull is disabled. Isjunk DEMO_MODE.")
    if not (WC_BASE_URL and WC_CK and WC_CS):
        raise RuntimeError("WC_BASE_URL/WC_CK/WC_CS not set")

    # atsargine kopija pries keitimus
    create_backup(label="before_wc_pull")

    session = get_session()
    woo = WooClient(base_url=WC_BASE_URL, consumer_key=WC_CK, consumer_secret=WC_CS)

    # paruosiam map'us is DB
    products = session.query(Product).all()
    by_wc_id = {p.wc_id: p for p in products if p.wc_id}
    by_norm_name = { " ".join(p.name.strip().lower().split()): p for p in products if p.name }

    def normalize(name: str) -> str:
        if not isinstance(name, str):
            return ""
        return " ".join(name.strip().lower().split())

    page = 1
    total_imported = 0
    while True:
        products = woo.list_products(page=page, per_page=100)
        if not products:
            break
        for item in products:
            wc_id = item.get("id")
            name = item.get("name")
            if not wc_id or not name:
                continue

            price_raw = item.get("regular_price")
            try:
                price = float(price_raw) if price_raw not in ("", None) else None
            except Exception:
                price = None
            quantity = item.get("stock_quantity")
            try:
                quantity = int(quantity) if quantity is not None else 0
            except Exception:
                quantity = 0
            sku = item.get("sku") or None

            norm = normalize(name)
            product = by_wc_id.get(wc_id) or by_norm_name.get(norm)

            if not product:
                product = Product(
                    name=name,
                    wc_id=wc_id,
                    sku=sku,
                    price=price,
                    quantity=quantity,
                    active=True,
                )
                session.add(product)
                if wc_id:
                    by_wc_id[wc_id] = product
                if norm:
                    by_norm_name[norm] = product
            else:
                # jeigu wc_id dar nesetintas, priskiriam
                if not product.wc_id and wc_id:
                    product.wc_id = wc_id
                    by_wc_id[wc_id] = product
                # judesio zurnalas tik jei keiciasi kiekis
                old_qty = product.quantity or 0
                if quantity != old_qty:
                    session.add(Movement(
                        product_id=product.id,
                        change=quantity - old_qty,
                        source="wc_pull",
                        note="Atnaujinta is WC",
                    ))
                product.name = product.name or name
                product.sku = sku or product.sku
                product.price = price
                product.quantity = quantity

            # raw saugojimas
            raw = session.query(WcProductRaw).filter(WcProductRaw.wc_id == wc_id).one_or_none()
            if raw:
                raw.raw = item
            else:
                session.add(WcProductRaw(wc_id=wc_id, raw=item))

            total_imported += 1
        page += 1

    session.commit()
    print(f"OK. Is WC atnaujinta/sukurta: {total_imported} irasu.")
