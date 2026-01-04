# sync_to_wc.py
import os

from models import get_session, Product
from woo_client import WooClient

DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"


def sync_prices_and_stock_to_wc():
    session = get_session()

    woo = None
    if DEMO_MODE:
        print("Demo mode: WooCommerce API calls are skipped.")
    else:
        woo = WooClient(
            base_url="https://TAVO-PARDUOTUVE.lt/",
            consumer_key="IRASYK_VELIAU",
            consumer_secret="IRASYK_VELIAU",
        )

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
