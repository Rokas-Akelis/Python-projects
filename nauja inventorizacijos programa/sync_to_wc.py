# sync_to_wc.py
import os
from models import get_session, Product, Movement, WcProductRaw, WcProductEdit
from woo_client import WooClient
from backup_utils import create_backup
from wc_fields import WC_EDIT_FIELDS

WC_BASE_URL = os.getenv("WC_BASE_URL")
WC_CK = os.getenv("WC_CK")
WC_CS = os.getenv("WC_CS")
WC_SYNC_IDS_RAW = os.getenv("WC_SYNC_IDS", "").strip()
WC_BATCH_SIZE_RAW = os.getenv("WC_BATCH_SIZE", "").strip()
WC_IMPORT_STATUS_RAW = os.getenv("WC_IMPORT_STATUS", "any").strip()


def _normalize_import_status(value: str | None) -> str | None:
    if value is None:
        return None
    status = str(value).strip().lower()
    return status or None


def _parse_batch_size(value, default=100) -> int:
    if value in (None, ""):
        return default
    try:
        size = int(value)
        if size <= 0:
            return default
        return size
    except Exception:
        return default


def _normalize_wc_sync_ids(value) -> set[int]:
    if value is None:
        return set()
    if isinstance(value, (set, list, tuple)):
        items = value
    else:
        raw = str(value).strip()
        if not raw:
            return set()
        items = raw.replace(";", ",").split(",")
    ids = set()
    for item in items:
        if isinstance(item, int):
            ids.add(int(item))
            continue
        part = str(item).strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return ids


DEFAULT_WC_SYNC_IDS = _normalize_wc_sync_ids(WC_SYNC_IDS_RAW)
WC_BATCH_SIZE = _parse_batch_size(WC_BATCH_SIZE_RAW, default=100)
WC_EDIT_FIELD_KEYS = {spec["key"] for spec in WC_EDIT_FIELDS}
WC_IMPORT_STATUS = _normalize_import_status(WC_IMPORT_STATUS_RAW)


def _wc_id_allowed(wc_id, allowed_ids: set[int]) -> bool:
    if not allowed_ids:
        return True
    try:
        return int(wc_id) in allowed_ids
    except Exception:
        return False


def _to_float(val):
    try:
        if val in ("", None):
            return None
        return float(val)
    except Exception:
        return None


def _to_int(val):
    try:
        if val in ("", None):
            return None
        return int(val)
    except Exception:
        try:
            return int(float(val))
        except Exception:
            return None


def _extract_raw_price_qty(raw):
    if not isinstance(raw, dict):
        return None, None, None
    raw_type = raw.get("type") or raw.get("Tipas")

    price = raw.get("regular_price")
    if price is None:
        price = raw.get("Reguliari kaina")
    if price is None:
        price = raw.get("Kaina")
    price = _to_float(price)

    qty = raw.get("stock_quantity")
    if qty is None:
        qty = raw.get("Atsargos")
    qty = _to_int(qty)

    return price, qty, raw_type


def _apply_edits_to_raw(raw: dict, edits: dict) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    for key, value in edits.items():
        if key not in WC_EDIT_FIELD_KEYS:
            continue
        if value is None:
            continue
        if key.startswith("dimensions."):
            dims = raw.get("dimensions")
            if not isinstance(dims, dict):
                dims = {}
            part = key.split(".", 1)[1]
            dims[part] = str(value)
            raw["dimensions"] = dims
            continue
        if key in {"regular_price", "sale_price"}:
            raw[key] = str(value)
            continue
        if key == "stock_quantity":
            raw[key] = int(value)
            continue
        if key == "manage_stock":
            raw[key] = bool(value)
            continue
        raw[key] = value
    return raw


def _build_wc_payload_from_edits(edits: dict) -> dict:
    payload = {}
    dimensions = {}
    for key, value in edits.items():
        if key not in WC_EDIT_FIELD_KEYS:
            continue
        if value is None:
            continue
        if key.startswith("dimensions."):
            part = key.split(".", 1)[1]
            dimensions[part] = str(value)
            continue
        if key in {"regular_price", "sale_price"}:
            payload[key] = str(value)
            continue
        if key == "stock_quantity":
            payload[key] = int(value)
            continue
        if key == "manage_stock":
            payload[key] = bool(value)
            continue
        payload[key] = value

    if dimensions:
        payload["dimensions"] = dimensions
    return payload


def _update_raw_after_push(session, wc_id, raw_obj, edits: dict):
    raw = raw_obj.raw if raw_obj and isinstance(raw_obj.raw, dict) else {}
    if not raw:
        raw = {"id": wc_id}
    raw = _apply_edits_to_raw(raw, edits)

    if raw_obj:
        raw_obj.raw = raw
    else:
        session.add(WcProductRaw(wc_id=wc_id, raw=raw))


def sync_wc_edits_to_wc(allowed_wc_ids=None, batch_size=None):
    session = get_session()

    if not (WC_BASE_URL and WC_CK and WC_CS):
        raise RuntimeError("WC_BASE_URL/WC_CK/WC_CS not set")
    woo = WooClient(base_url=WC_BASE_URL, consumer_key=WC_CK, consumer_secret=WC_CS)

    allowed_ids = DEFAULT_WC_SYNC_IDS if allowed_wc_ids is None else _normalize_wc_sync_ids(allowed_wc_ids)
    if allowed_ids:
        print(f"Filtras aktyvus (WC_SYNC_IDS): {sorted(allowed_ids)}")

    batch_size = _parse_batch_size(batch_size, default=WC_BATCH_SIZE)
    raw_rows = session.query(WcProductRaw).all()
    raw_by_wc = {r.wc_id: r for r in raw_rows if r.wc_id}
    edit_rows = session.query(WcProductEdit).all()
    if not edit_rows:
        print("Nera pakeitimu sinchronizavimui.")
        return

    batch_updates = []
    batch_meta = {}
    raw_dirty = False
    edits_dirty = False

    def flush_batch():
        nonlocal raw_dirty, edits_dirty
        if not batch_updates:
            return
        try:
            result = woo.update_products_batch(batch_updates)
        except Exception as e:
            print(f"Klaida WC batch atnaujinant {len(batch_updates)} produktu: {e}")
            batch_updates.clear()
            batch_meta.clear()
            return

        if isinstance(result, dict):
            update_items = result.get("update") or []
        elif isinstance(result, list):
            update_items = result
        else:
            update_items = []

        success_ids = set()
        error_ids = set()
        for item in update_items:
            if not isinstance(item, dict):
                continue
            wc_id = item.get("id")
            try:
                wc_id = int(wc_id)
            except Exception:
                continue
            if "error" in item:
                error_ids.add(wc_id)
                err = item.get("error")
                msg = err.get("message") if isinstance(err, dict) else str(err)
                print(f"Klaida WC atnaujinant (ID={wc_id}): {msg}")
                continue
            success_ids.add(wc_id)

        if not update_items:
            print(f"WC batch atsakymas tuscias, nepatvirtinti {len(batch_updates)} atnaujinimai.")

        for wc_id, meta in batch_meta.items():
            if update_items:
                if wc_id in error_ids:
                    continue
                if success_ids and wc_id not in success_ids:
                    print(f"WC ID={wc_id}: atnaujinimas nepatvirtintas, DB nelieciama.")
                    continue
            else:
                continue

            edits = meta["edits"]
            changed_keys = ", ".join(sorted(edits.keys())) if edits else "-"
            print(f"OK. WC_ID={wc_id} atnaujinta: {changed_keys}")

            _update_raw_after_push(session, wc_id, meta["raw_obj"], edits)
            if meta.get("edit_obj") is not None:
                session.delete(meta["edit_obj"])
            raw_dirty = True
            edits_dirty = True

        batch_updates.clear()
        batch_meta.clear()

    for edit in edit_rows:
        wc_id = getattr(edit, "wc_id", None)
        if not wc_id:
            continue
        if not _wc_id_allowed(wc_id, allowed_ids):
            continue
        raw_obj = raw_by_wc.get(wc_id)
        if raw_obj is None:
            print(f"WC ID={wc_id}: nerasta importuotu duomenu, praleidziama.")
            continue

        edits = edit.edits or {}
        if not isinstance(edits, dict) or not edits:
            continue

        payload = _build_wc_payload_from_edits(edits)
        if not payload:
            continue

        payload["id"] = int(wc_id)
        batch_updates.append(payload)
        batch_meta[int(wc_id)] = {
            "raw_obj": raw_obj,
            "edit_obj": edit,
            "edits": edits,
        }

        if len(batch_updates) >= batch_size:
            flush_batch()

    flush_batch()
    if raw_dirty or edits_dirty:
        session.commit()


def sync_prices_and_stock_to_wc(allowed_wc_ids=None, batch_size=None):
    return sync_wc_edits_to_wc(allowed_wc_ids=allowed_wc_ids, batch_size=batch_size)

    if not (WC_BASE_URL and WC_CK and WC_CS):
        raise RuntimeError("WC_BASE_URL/WC_CK/WC_CS not set")
    woo = WooClient(base_url=WC_BASE_URL, consumer_key=WC_CK, consumer_secret=WC_CS)

    allowed_ids = DEFAULT_WC_SYNC_IDS if allowed_wc_ids is None else _normalize_wc_sync_ids(allowed_wc_ids)
    if allowed_ids:
        print(f"Filtras aktyvus (WC_SYNC_IDS): {sorted(allowed_ids)}")

    batch_size = _parse_batch_size(batch_size, default=WC_BATCH_SIZE)
    products = session.query(Product).filter(Product.active == True).all()
    batch_updates = []
    batch_meta = {}
    raw_dirty = False

    def flush_batch():
        nonlocal raw_dirty
        if not batch_updates:
            return
        try:
            result = woo.update_products_batch(batch_updates)
        except Exception as e:
            print(f"Klaida WC batch atnaujinant {len(batch_updates)} produktu: {e}")
            batch_updates.clear()
            batch_meta.clear()
            return

        if isinstance(result, dict):
            update_items = result.get("update") or []
        elif isinstance(result, list):
            update_items = result
        else:
            update_items = []

        success_ids = set()
        error_ids = set()
        for item in update_items:
            if not isinstance(item, dict):
                continue
            wc_id = item.get("id")
            try:
                wc_id = int(wc_id)
            except Exception:
                continue
            if "error" in item:
                error_ids.add(wc_id)
                err = item.get("error")
                msg = err.get("message") if isinstance(err, dict) else str(err)
                name = batch_meta.get(wc_id, {}).get("name", "?")
                print(f"Klaida WC atnaujinant {name} (ID={wc_id}): {msg}")
                continue
            success_ids.add(wc_id)

        if not update_items:
            print(f"WC batch atsakymas tuscias, nepatvirtinti {len(batch_updates)} atnaujinimai.")

        for wc_id, meta in batch_meta.items():
            if update_items:
                if wc_id in error_ids:
                    continue
                if success_ids and wc_id not in success_ids:
                    print(f"WC ID={wc_id}: atnaujinimas nepatvirtintas, DB nelieciama.")
                    continue
            else:
                continue

            prev_price = meta["prev_price"]
            prev_qty = meta["prev_qty"]
            send_price = meta["send_price"]
            send_qty = meta["send_qty"]
            name = meta["name"]
            price = meta["price"]
            quantity = meta["quantity"]

            print(
                f"OK. WC_ID={wc_id} ({name})"
                f" price {prev_price}->{price if send_price is not None else prev_price},"
                f" qty {prev_qty}->{quantity if send_qty is not None else prev_qty}"
            )

            _update_raw_after_push(session, wc_id, meta["raw_obj"], send_price, send_qty)
            raw_dirty = True

        batch_updates.clear()
        batch_meta.clear()

    for p in products:
        if not p.wc_id:
            continue
        if not _wc_id_allowed(p.wc_id, allowed_ids):
            continue

        try:
            raw_obj = session.query(WcProductRaw).filter(WcProductRaw.wc_id == p.wc_id).one_or_none()
            raw_price, raw_qty, raw_type = _extract_raw_price_qty(raw_obj.raw if raw_obj else None)

            price_changed = p.price is not None and (raw_price is None or abs(p.price - raw_price) > 0.0001)
            qty_changed = p.quantity is not None and (raw_qty is None or int(p.quantity) != raw_qty)

            if not price_changed and not qty_changed:
                print(f"WC ID={p.wc_id}: nera pokyciu (price={p.price}, qty={p.quantity}).")
                continue

            wc_type = raw_type
            current = None
            if wc_type is None:
                try:
                    current = woo.get_product(p.wc_id)
                except Exception as e_get:
                    print(f"WC ID={p.wc_id}: nepavyko perskaityti esamo produkto ({e_get}), bandome vis tiek atnaujinti.")
                if isinstance(current, dict):
                    wc_type = current.get("type")
                    if raw_price is None:
                        raw_price = _to_float(current.get("regular_price"))
                    if raw_qty is None:
                        raw_qty = _to_int(current.get("stock_quantity"))
                    price_changed = p.price is not None and (
                        raw_price is None or abs(p.price - raw_price) > 0.0001
                    )
                    qty_changed = p.quantity is not None and (
                        raw_qty is None or int(p.quantity) != raw_qty
                    )
                    if not price_changed and not qty_changed:
                        print(f"WC ID={p.wc_id}: nera pokyciu (price={p.price}, qty={p.quantity}).")
                        continue

            if wc_type and wc_type not in {"simple"}:
                print(f"WC ID={p.wc_id}: type={wc_type} nepalaikomas (variacija/variable). Šiuo metu neatnaujinama.")
                continue

            send_price = p.price if price_changed else None
            send_qty = p.quantity if qty_changed else None
            if send_price is None and send_qty is None:
                continue

            payload = {"id": int(p.wc_id)}
            if send_price is not None:
                payload["regular_price"] = str(send_price)
            if send_qty is not None:
                payload["stock_quantity"] = int(send_qty)
                payload["manage_stock"] = True

            batch_updates.append(payload)
            batch_meta[int(p.wc_id)] = {
                "name": p.name,
                "prev_price": raw_price if raw_price is not None else "-",
                "prev_qty": raw_qty if raw_qty is not None else "-",
                "send_price": send_price,
                "send_qty": send_qty,
                "price": p.price,
                "quantity": p.quantity,
                "raw_obj": raw_obj,
            }

            if len(batch_updates) >= batch_size:
                flush_batch()
        except Exception as e:
            # jei 404 - WC pusėje nėra tokio ID, tiesiog praleidžiam nekeičiant DB
            if hasattr(e, "response") and getattr(e.response, "status_code", None) == 404:
                print(f"WC ID={p.wc_id} nerastas (404). Praleidžiama, DB neliečiama: {p.name}")
                continue
            print(f"Klaida WC atnaujinant {p.name}: {e}")

    flush_batch()
    if raw_dirty:
        session.commit()


def pull_products_from_wc():
    """
    Persikrauna duomenis is WooCommerce i DB:
    - WC API -> atnaujinanuraria Product
    - Issaugo pilna raw JSON i wc_raw_products
    - Kiekiu pokycius zymi Movement
    """
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
        products = woo.list_products(page=page, per_page=100, status=WC_IMPORT_STATUS)
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
            quantity_raw = item.get("stock_quantity")
            quantity = _to_int(quantity_raw) if quantity_raw is not None else None
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
                if quantity is not None:
                    old_qty = product.quantity or 0
                    if quantity != old_qty:
                        session.add(Movement(
                            product_id=product.id,
                            change=quantity - old_qty,
                            source="wc_pull",
                            note="Atnaujinta is WC",
                        ))
                    product.quantity = quantity
                product.name = name
                product.sku = sku or product.sku
                product.price = price

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
