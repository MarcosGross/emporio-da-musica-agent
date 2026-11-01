"""Agent tools as plain Python functions.

Every tool returns a JSON-serializable dict with English keys. Prices,
discounts and installments come from pricing.py — never from the LLM.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from functools import lru_cache

import pandas as pd

from emporio_agent import data as store
from emporio_agent.pricing import final_price, installment_value, max_installments, pix_price

SEARCH_LIMIT = 10
MAX_ALTERNATIVES = 3
MAX_CANDIDATES = 10
FUZZY_TOKEN_CUTOFF = 0.75

ORDER_NOT_FOUND = {
    "found": False,
    "error": "order_not_found_or_contact_mismatch",
    "message": "No order matches this order id and contact.",
}


@lru_cache(maxsize=1)
def _data() -> store.StoreData:
    return store.load_data()


# --- Normalization helpers --------------------------------------------------

def normalize_text(text: str) -> str:
    """Lowercase, strip accents and collapse punctuation to single spaces."""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def normalize_phone(phone: str) -> str:
    """Digits only, without the Brazil country code (55)."""
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) in (12, 13) and digits.startswith("55"):
        digits = digits[2:]
    return digits


def normalize_email(email: str) -> str:
    return str(email).strip().lower()


def _clean(value):
    """Convert pandas/numpy scalars to JSON-friendly Python values."""
    if value is None or (not isinstance(value, (dict, list)) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


# --- Product formatting -----------------------------------------------------

def _category_names() -> dict[int, str]:
    categories = _data().categories
    return dict(zip(categories["category_id"].astype(int), categories["name"]))


def _availability(product: pd.Series) -> str:
    if product["status"] == "discontinued":
        return "discontinued"
    if product["status"] == "coming_soon":
        return "coming_soon"
    if store.is_sellable(product):
        return "available"
    return "out_of_stock"


def _product_item(product: pd.Series) -> dict:
    """Sellable product with its full price breakdown."""
    promo = store.active_promotion(_data(), int(product["product_id"]))
    quote = final_price(product, promo)
    pix = pix_price(product, promo)
    installments = max_installments(quote.final_price)
    item = {
        "id": int(product["product_id"]),
        "name": product["name"],
        "category": _category_names().get(int(product["category_id"])),
        "specs": product["specs"],
        "original_price_brl": float(quote.original_price),
        "promotion_discount_percent": float(quote.discount_percent),
        "promotion_name": quote.promotion,
        "final_price_brl": float(quote.final_price),
        "pix_price_brl": float(pix.final_price),
        "max_installments": installments,
        "installment_value_brl": float(installment_value(quote.final_price, installments)),
    }
    if product["description_reliable"]:
        item["description"] = product["description"]
    return item


def _product_summary(product: pd.Series) -> dict:
    """Identification only, no prices: used for unavailable products and candidates."""
    return {
        "id": int(product["product_id"]),
        "name": product["name"],
        "category": _category_names().get(int(product["category_id"])),
        "availability": _availability(product),
    }


def _sellable_products() -> pd.DataFrame:
    products = _data().products
    return products[(products["status"] == "active") & (products["stock_quantity"] > 0)]


# --- Tools ------------------------------------------------------------------

def list_categories() -> dict:
    """All categories with the number of sellable products in each."""
    counts = _sellable_products()["category_id"].value_counts()
    categories = [
        {
            "id": int(row.category_id),
            "name": row.name,
            "description": row.description,
            "sellable_products": int(counts.get(row.category_id, 0)),
        }
        for row in _data().categories.itertuples()
    ]
    return {"categories": categories}


def _match_categories(category: str | int) -> list[int]:
    """Category ids matching an id, an exact/partial name or a close spelling."""
    names = _category_names()
    if isinstance(category, int) or str(category).strip().isdigit():
        return [int(category)] if int(category) in names else []

    query = normalize_text(category)
    normalized = {cid: normalize_text(name) for cid, name in names.items()}
    exact = [cid for cid, name in normalized.items() if name == query]
    if exact:
        return exact
    partial = [cid for cid, name in normalized.items() if query in name]
    if partial:
        return partial
    return [cid for cid, name in normalized.items()
            if any(difflib.get_close_matches(q, name.split(), n=1, cutoff=FUZZY_TOKEN_CUTOFF)
                   for q in query.split())]


def _searchable_text(product: pd.Series) -> str:
    parts = [product["name"], *map(str, product["specs"].values())]
    if product["description_reliable"]:
        parts.append(product["description"])
    return normalize_text(" ".join(parts))


def search_products(category: str | int | None = None, max_price: float | None = None,
                    min_price: float | None = None, query: str | None = None) -> dict:
    """Sellable products filtered by category, final price range and free text.

    Sorted by final price (ascending), at most SEARCH_LIMIT items; `total`
    is the number of matches before the limit.
    """
    products = _sellable_products()
    filters = {"category": category, "min_price": min_price, "max_price": max_price, "query": query}

    if category is not None:
        category_ids = _match_categories(category)
        if not category_ids:
            return {"filters": filters, "error": "unknown_category",
                    "available_categories": list(_category_names().values()),
                    "total": 0, "returned": 0, "products": []}
        products = products[products["category_id"].isin(category_ids)]

    if query:
        tokens = normalize_text(query).split()
        products = products[[all(t in _searchable_text(p) for t in tokens)
                             for _, p in products.iterrows()]]

    items = [_product_item(p) for _, p in products.iterrows()]
    if min_price is not None:
        items = [i for i in items if i["final_price_brl"] >= min_price]
    if max_price is not None:
        items = [i for i in items if i["final_price_brl"] <= max_price]
    items.sort(key=lambda i: (i["final_price_brl"], i["id"]))

    return {"filters": filters, "total": len(items), "returned": min(len(items), SEARCH_LIMIT),
            "products": items[:SEARCH_LIMIT]}


def _find_products(name_or_id: str | int) -> pd.DataFrame:
    """Products matching an id, all query tokens (as substrings) or close spellings."""
    products = _data().products
    text = str(name_or_id).strip()
    if text.lstrip("#").isdigit():
        return products[products["product_id"] == int(text.lstrip("#"))]

    tokens = normalize_text(text).split()
    if not tokens:
        return products.iloc[0:0]
    names = products["name"].map(normalize_text)

    exact = products[names == " ".join(tokens)]
    if not exact.empty:
        return exact

    substring = products[[all(t in n for t in tokens) for n in names]]
    if not substring.empty:
        return substring

    def fuzzy_match(name: str) -> bool:
        words = name.split()
        return all(difflib.get_close_matches(t, words, n=1, cutoff=FUZZY_TOKEN_CUTOFF) for t in tokens)

    return products[[fuzzy_match(n) for n in names]]


def _alternatives(product: pd.Series) -> list[dict]:
    """Sellable products of the same category, closest in price first."""
    reference = float(final_price(product, store.active_promotion(_data(), int(product["product_id"]))).final_price)
    same_category = _sellable_products()
    same_category = same_category[(same_category["category_id"] == product["category_id"])
                                  & (same_category["product_id"] != product["product_id"])]
    items = [_product_item(p) for _, p in same_category.iterrows()]
    items.sort(key=lambda i: (abs(i["final_price_brl"] - reference), i["final_price_brl"]))
    return items[:MAX_ALTERNATIVES]


def get_product(name_or_id: str | int) -> dict:
    """One product by id or approximate name, with availability and alternatives."""
    matches = _find_products(name_or_id)

    if matches.empty:
        return {"query": str(name_or_id), "availability": "not_found"}

    if len(matches) > 1:
        candidates = [_product_summary(p) for _, p in matches.head(MAX_CANDIDATES).iterrows()]
        return {"query": str(name_or_id), "availability": "ambiguous",
                "total_candidates": len(matches), "candidates": candidates}

    product = matches.iloc[0]
    availability = _availability(product)
    if availability == "available":
        return {"query": str(name_or_id), "availability": availability, "product": _product_item(product)}

    result = _product_summary(product)
    result["specs"] = product["specs"]
    return {"query": str(name_or_id), "availability": availability, "product": result,
            "alternatives": _alternatives(product)}


def _contact_matches(customer: pd.Series, contact: str) -> bool:
    contact = str(contact or "").strip()
    if "@" in contact:
        return normalize_email(contact) == normalize_email(customer["email"])
    digits = normalize_phone(contact)
    return bool(digits) and digits == normalize_phone(customer["phone"])


def get_order_status(order_id: str | int, contact: str) -> dict:
    """Order details, only when the contact (e-mail or phone) belongs to the order's customer.

    A missing order and a wrong contact return the same error, so the response
    never reveals whether an order id exists.
    """
    data = _data()
    order_text = str(order_id).strip().lstrip("#")
    if not order_text.isdigit():
        return dict(ORDER_NOT_FOUND)

    orders = data.orders[data.orders["order_id"] == int(order_text)]
    if orders.empty:
        return dict(ORDER_NOT_FOUND)
    order = orders.iloc[0]

    customers = data.customers[data.customers["customer_id"] == order["customer_id"]]
    if customers.empty or not _contact_matches(customers.iloc[0], contact):
        return dict(ORDER_NOT_FOUND)

    items = data.order_items[data.order_items["order_id"] == order["order_id"]]
    items = items.merge(data.products[["product_id", "name"]], on="product_id", how="left")

    return {
        "found": True,
        "order_id": int(order["order_id"]),
        "status": order["status"],
        "order_date": _clean(order["order_date"]),
        "items": [{"product_name": _clean(i.name), "quantity": int(i.quantity)} for i in items.itertuples()],
        "total_brl": float(order["total_brl"]),
        "payment_method": order["payment_method"],
        "tracking_code": _clean(order["tracking_code"]),
        "estimated_delivery": _clean(order["estimated_delivery"]),
        "notes": _clean(order["notes"]),
    }
