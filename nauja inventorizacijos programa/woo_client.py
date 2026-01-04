# woo_client.py
import requests
from urllib.parse import urljoin

class WooClient:
    def __init__(self, base_url: str, consumer_key: str, consumer_secret: str):
        # pvz base_url = "https://mano-parduotuve.lt/"
        if not base_url.endswith("/"):
            base_url += "/"
        self.base_url = base_url
        self.ck = consumer_key
        self.cs = consumer_secret

    def _auth_params(self):
        return {
            "ck_0cb3e88fd23aeff0d7904e1c96b9d8b09127dcf1": self.ck,
            "cs_f51a500ae54bf5ffd62a50d50c70ee86cb38fa44": self.cs,
        }

    def update_product(self, wc_id: int, data: dict):
        url = urljoin(self.base_url, f"wp-json/wc/v3/products/{wc_id}")
        params = self._auth_params()
        resp = requests.put(url, params=params, json=data)
        resp.raise_for_status()
        return resp.json()

    def list_products(self, per_page: int = 100, page: int = 1):
        url = urljoin(self.base_url, "wp-json/wc/v3/products")
        params = self._auth_params() | {"per_page": per_page, "page": page}
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def update_price_and_stock(self, wc_id: int, price: float | None, quantity: int | None):
        payload = {}
        if price is not None:
            payload["regular_price"] = str(price)
        if quantity is not None:
            payload["stock_quantity"] = quantity
            payload["manage_stock"] = True

        if not payload:
            return None

        return self.update_product(wc_id, payload)
