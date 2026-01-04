# sync_to_wc.py
import os

import os
from models import get_session, Product, Movement, WcProductRaw
from woo_client import WooClient
from backup_utils import create_backup

DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"
WC_BASE_URL = os.getenv("WC_BASE_URL", "https://TAVO-PARDUOTUVE.lt/")
WC_CK = os.getenv("WC_CONSUMER_KEY") or os.getenv("WC_CK")
WC_CS = os.getenv("WC_CONSUMER_SECRET") or os.getenv("WC_CS")


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
            woo.update_price_and_stock(
                wc_id=p.wc_id,
                price=p.price,
                quantity=p.quantity,
            )
            print(f"OK. Atnaujinta WC preke ID={p.wc_id} ({p.name})")
        except Exception as e:
            print(f"Klaida WC atnaujinant {p.name}: {e}")


def pull_products_from_wc():
    """
    Persikrauna duomenis is WooCommerce i DB:
    - WC API -> atnaujina/kuria Product
    - Issaugo pilna raw JSON i wc_raw_products
    - Kiekiu pokycius zymi Movement
    """
    if DEMO_MODE:
        raise RuntimeError("Demo mode: WC pull is disabled. Išjunk DEMO_MODE.")
    if not (WC_BASE_URL and WC_CK and WC_CS):
        raise RuntimeError("WC_BASE_URL/WC_CK/WC_CS not set")

    # atsargine kopija pries keitimus
    create_backup(label="before_wc_pull")

    session = get_session()
    woo = WooClient(base_url=WC_BASE_URL, consumer_key=WC_CK, consumer_secret=WC_CS)

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

            product = session.query(Product).filter(Product.wc_id == wc_id).one_or_none()
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
            else:
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
    print(f"OK. Iš WC atnaujinta/sukurta: {total_imported} įrašų.")
