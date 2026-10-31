"""Loading of the store's raw CSVs and data quality checks.

The raw files keep the export prefix ("desafio_tecnico_ai_eng - products.csv");
internally every table is addressed by its short name ("products").
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from emporio_agent.pricing import MAX_INSTALLMENTS, installment_value, min_installment_value

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

TABLES = ("categories", "customers", "orders", "order_items", "products", "promotions")

# Brands carried by the catalog, plus brands that only show up in descriptions.
KNOWN_BRANDS = (
    "Music Man", "Yamaha", "Tagima", "Giannini", "Rozini", "Shelby", "Crafter",
    "Martin", "Taylor", "Takamine", "Kala", "Kalani", "Ohana", "Fender", "Gibson",
    "Ibanez", "PRS", "Pearl", "Tama", "Korg", "Nord", "Roland",
)

# Model lines that identify a brand even when the brand itself is not written.
MODEL_BRANDS = {
    "Stratocaster": "Fender",
    "Telecaster": "Fender",
    "Jazz Bass": "Fender",
    "Precision": "Fender",
    "Les Paul": "Gibson",
    "StingRay": "Music Man",
    "Stage Custom": "Yamaha",
    "Export": "Pearl",
    "Star-Mount": "Tama",
    "SuperNATURAL": "Roland",
}


@dataclass(frozen=True)
class StoreData:
    categories: pd.DataFrame
    customers: pd.DataFrame
    orders: pd.DataFrame
    order_items: pd.DataFrame
    products: pd.DataFrame
    promotions: pd.DataFrame


def table_name(path: Path) -> str:
    """Map "desafio_tecnico_ai_eng - order_items.csv" to "order_items"."""
    stem = path.stem.split(" - ")[-1]
    return re.sub(r"[^a-z0-9]+", "_", stem.strip().lower()).strip("_")


def load_data(data_dir: str | Path | None = None) -> StoreData:
    data_dir = Path(data_dir or os.getenv("EMPORIO_DATA_DIR") or DEFAULT_DATA_DIR)
    frames = {table_name(p): pd.read_csv(p, encoding="utf-8") for p in data_dir.glob("*.csv")}

    missing = set(TABLES) - frames.keys()
    if missing:
        raise FileNotFoundError(f"Missing tables in {data_dir}: {sorted(missing)}")

    frames["products"] = _prepare_products(frames["products"])
    frames["orders"] = _prepare_orders(frames["orders"])
    return StoreData(**{name: frames[name] for name in TABLES})


def _prepare_products(products: pd.DataFrame) -> pd.DataFrame:
    products = products.copy()
    products["specs"] = products["specs"].map(_parse_specs)
    products["created_at"] = pd.to_datetime(products["created_at"])

    issues = [_description_brand_issue(r.name, r.description) for r in products.itertuples()]
    products["description_issue"] = issues
    products["description_reliable"] = [issue is None for issue in issues]
    return products.sort_values("product_id").reset_index(drop=True)


def _prepare_orders(orders: pd.DataFrame) -> pd.DataFrame:
    orders = orders.copy()
    for col in ("order_date", "estimated_delivery"):
        orders[col] = pd.to_datetime(orders[col])
    return orders


def _parse_specs(raw: object) -> dict:
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _brands_in(text: str) -> set[str]:
    found = {b for b in KNOWN_BRANDS if re.search(rf"\b{re.escape(b)}\b", text)}
    found |= {b for model, b in MODEL_BRANDS.items() if re.search(rf"\b{re.escape(model)}\b", text)}
    return found


def brand_from_name(name: str) -> str | None:
    """First known brand appearing in the product name, by position."""
    hits = [(m.start(), b) for b in KNOWN_BRANDS if (m := re.search(rf"\b{re.escape(b)}\b", name))]
    return min(hits)[1] if hits else None


def _description_brand_issue(name: str, description: str) -> str | None:
    name_brand = brand_from_name(name)
    if name_brand is None or not isinstance(description, str):
        return None
    conflicting = _brands_in(description) - {name_brand}
    if not conflicting:
        return None
    return f"name says {name_brand}, description mentions {', '.join(sorted(conflicting))}"


# --- Business helpers -------------------------------------------------------

def is_sellable(product: pd.Series | dict) -> bool:
    return product["status"] == "active" and int(product["stock_quantity"]) > 0


def get_product(data: StoreData, product_id: int) -> pd.Series | None:
    rows = data.products[data.products["product_id"] == product_id]
    return None if rows.empty else rows.iloc[0]


def active_promotion(data: StoreData, product_id: int) -> pd.Series | None:
    """The product's active promotion (highest discount if several), or None."""
    promos = data.promotions
    rows = promos[(promos["product_id"] == product_id) & (promos["is_active"] == 1)]
    if rows.empty:
        return None
    return rows.sort_values("discount_percent", ascending=False).iloc[0]


# --- Data quality report ----------------------------------------------------

def active_out_of_stock(data: StoreData) -> pd.DataFrame:
    p = data.products
    return p.loc[(p["status"] == "active") & (p["stock_quantity"] == 0),
                 ["product_id", "name", "status", "stock_quantity"]]


def discontinued_with_stock(data: StoreData) -> pd.DataFrame:
    p = data.products
    return p.loc[(p["status"] == "discontinued") & (p["stock_quantity"] > 0),
                 ["product_id", "name", "status", "stock_quantity"]]


def order_total_mismatches(data: StoreData, tolerance: float = 0.01) -> pd.DataFrame:
    """Orders whose total_brl differs from sum(quantity * current price_brl).

    A warning, not an error: there is no price history, so a gap may be a
    discount or price change at purchase time. Orders are shown as recorded.
    """
    items = data.order_items.merge(data.products[["product_id", "price_brl"]], on="product_id", how="left")
    items["line_total"] = items["quantity"] * items["price_brl"]
    sums = items.groupby("order_id", as_index=False)["line_total"].sum(min_count=1)
    sums = sums.rename(columns={"line_total": "items_total_brl"})

    merged = data.orders[["order_id", "status", "total_brl"]].merge(sums, on="order_id", how="left")
    merged["difference_brl"] = (merged["total_brl"] - merged["items_total_brl"]).round(2)
    mismatch = merged["items_total_brl"].isna() | (merged["difference_brl"].abs() > tolerance)
    return merged.loc[mismatch].reset_index(drop=True)


def installment_rule_violations(data: StoreData) -> pd.DataFrame:
    """Credit orders whose installment is below the manual 3.1 minimum.

    The rules govern new quotes only; historical orders are kept as recorded.
    """
    orders = data.orders[["order_id", "status", "total_brl", "payment_method"]].copy()
    installments = orders["payment_method"].str.extract(r"^credit_(\d+)x$", expand=False)
    orders = orders[installments.notna()].assign(installments=installments.dropna().astype(int))

    orders["installment_brl"] = [float(installment_value(t, n))
                                 for t, n in zip(orders["total_brl"], orders["installments"])]
    orders["min_installment_brl"] = [float(min_installment_value(n)) if n <= MAX_INSTALLMENTS else None
                                     for n in orders["installments"]]
    violation = orders["min_installment_brl"].isna() | (orders["installment_brl"] < orders["min_installment_brl"])
    return orders.loc[violation].reset_index(drop=True)


def orders_with_unreleased_products(data: StoreData) -> pd.DataFrame:
    """Order items pointing to products that are not released yet (or missing from the catalog)."""
    items = data.order_items.merge(data.products[["product_id", "name", "status"]], on="product_id", how="left")
    items = items.merge(data.orders[["order_id", "order_date"]], on="order_id", how="left")
    items = items.rename(columns={"status": "product_status"})
    flagged = items["product_status"].isna() | (items["product_status"] == "coming_soon")
    return items.loc[flagged, ["order_id", "order_date", "product_id", "name", "product_status"]].reset_index(drop=True)


def duplicated_customer_emails(data: StoreData) -> pd.DataFrame:
    c = data.customers.assign(email_normalized=data.customers["email"].str.strip().str.lower())
    dupes = c[c.duplicated("email_normalized", keep=False)]
    return dupes[["customer_id", "name", "email", "phone"]].sort_values("email").reset_index(drop=True)


def unreliable_descriptions(data: StoreData) -> pd.DataFrame:
    p = data.products
    return p.loc[~p["description_reliable"], ["product_id", "name", "description_issue"]].reset_index(drop=True)


def data_quality_report(data: StoreData) -> dict[str, pd.DataFrame]:
    return {
        "active_out_of_stock": active_out_of_stock(data),
        "discontinued_with_stock": discontinued_with_stock(data),
        "order_total_mismatches": order_total_mismatches(data),
        "installment_rule_violations": installment_rule_violations(data),
        "orders_with_unreleased_products": orders_with_unreleased_products(data),
        "duplicated_customer_emails": duplicated_customer_emails(data),
        "unreliable_descriptions": unreliable_descriptions(data),
    }
