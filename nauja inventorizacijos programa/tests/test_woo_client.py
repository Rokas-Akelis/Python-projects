from woo_client import WooClient
import woo_client


def test_update_price_and_stock_builds_payload():
    calls = []

    class TestClient(WooClient):
        def update_product(self, wc_id, data):
            calls.append((wc_id, data))
            return {"ok": True}

    client = TestClient("https://example.com", "ck", "cs")
    client.update_price_and_stock(5, price=9.99, quantity=7)

    assert calls == [
        (
            5,
            {
                "regular_price": "9.99",
                "stock_quantity": 7,
                "manage_stock": True,
            },
        )
    ]


def test_update_price_and_stock_empty_payload():
    calls = []

    class TestClient(WooClient):
        def update_product(self, wc_id, data):
            calls.append((wc_id, data))
            return {"ok": True}

    client = TestClient("https://example.com", "ck", "cs")
    result = client.update_price_and_stock(5, price=None, quantity=None)

    assert result is None
    assert calls == []


def test_update_product_calls_requests(monkeypatch):
    calls = {}

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def fake_put(url, auth=None, json=None):
        calls["url"] = url
        calls["auth"] = auth
        calls["json"] = json
        return FakeResp()

    monkeypatch.setattr(woo_client.requests, "put", fake_put)

    client = WooClient("https://example.com", "ck", "cs")
    resp = client.update_product(12, {"a": 1})

    assert resp == {"ok": True}
    assert calls["url"].endswith("/wp-json/wc/v3/products/12")
    assert calls["auth"] == ("ck", "cs")
    assert calls["json"] == {"a": 1}


def test_get_and_list_products_calls_requests(monkeypatch):
    calls = {"get": []}

    class FakeResp:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, auth=None, params=None):
        calls["get"].append({"url": url, "auth": auth, "params": params})
        payload = {"id": 1} if params is None else []
        return FakeResp(payload)

    monkeypatch.setattr(woo_client.requests, "get", fake_get)

    client = WooClient("https://example.com", "ck", "cs")
    prod = client.get_product(1)
    assert prod == {"id": 1}

    products = client.list_products(per_page=50, page=2)
    assert products == []

    assert calls["get"][0]["url"].endswith("/wp-json/wc/v3/products/1")
    assert calls["get"][1]["url"].endswith("/wp-json/wc/v3/products")
    assert calls["get"][1]["params"] == {"per_page": 50, "page": 2}
