# wc_fields.py
from __future__ import annotations

from typing import Any


WC_EDIT_FIELDS = [
    {"key": "name", "label": "Pavadinimas", "type": "text"},
    {"key": "description", "label": "Aprašymas", "type": "text"},
    {"key": "short_description", "label": "Trumpas aprašymas", "type": "text"},
    {"key": "regular_price", "label": "Reguliari kaina", "type": "price"},
    {"key": "sale_price", "label": "Akcijos kaina", "type": "price"},
    {"key": "date_on_sale_from", "label": "Akcija nuo", "type": "date"},
    {"key": "date_on_sale_to", "label": "Akcija iki", "type": "date"},
    {"key": "manage_stock", "label": "Valdyti atsargas", "type": "bool"},
    {"key": "stock_quantity", "label": "Atsargos", "type": "int"},
    {"key": "dimensions.length", "label": "Ilgis", "type": "float"},
    {"key": "dimensions.width", "label": "Plotis", "type": "float"},
    {"key": "dimensions.height", "label": "Aukštis", "type": "float"},
    {"key": "purchase_note", "label": "Komentaras", "type": "text"},
]


WC_FIELD_ALIASES = {
    "name": ["name", "Pavadinimas"],
    "description": ["description", "Aprašymas"],
    "short_description": ["short_description", "Trumpas aprašymas", "Short description"],
    "regular_price": ["regular_price", "Reguliari kaina", "Kaina"],
    "sale_price": ["sale_price", "Akcijos kaina", "Sale price"],
    "date_on_sale_from": ["date_on_sale_from", "Akcija nuo", "Sale from"],
    "date_on_sale_to": ["date_on_sale_to", "Akcija iki", "Sale to"],
    "manage_stock": ["manage_stock", "Valdyti atsargas"],
    "stock_quantity": ["stock_quantity", "Atsargos"],
    "dimensions.length": ["dimensions.length", "Ilgis"],
    "dimensions.width": ["dimensions.width", "Plotis"],
    "dimensions.height": ["dimensions.height", "Aukštis"],
    "purchase_note": ["purchase_note", "Komentaras", "Komentarai", "Pastaba", "Pastabos", "comment"],
    "price": ["price", "Kaina"],
}


def get_raw_value(raw: dict | None, key: str) -> Any:
    if not isinstance(raw, dict):
        return None

    if key.startswith("dimensions."):
        dims = raw.get("dimensions")
        if isinstance(dims, dict):
            part = key.split(".", 1)[1]
            if part in dims:
                return dims.get(part)

    if key in raw:
        return raw.get(key)

    for alias in WC_FIELD_ALIASES.get(key, []):
        if alias in raw:
            return raw.get(alias)
    return None
