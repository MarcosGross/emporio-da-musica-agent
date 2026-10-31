from dataclasses import replace
from pathlib import Path

import pandas as pd

from emporio_agent.data import (
    TABLES, active_promotion, data_quality_report, get_product, is_sellable, table_name,
)


def test_file_names_are_normalized(data):
    assert table_name(Path("desafio_tecnico_ai_eng - order_items.csv")) == "order_items"
    assert all(len(getattr(data, t)) > 0 for t in TABLES)


def test_specs_are_parsed_to_dict(data):
    specs = get_product(data, 81)["specs"]
    assert isinstance(specs, dict)
    assert specs["strings"] == "nylon"


def test_product_96_not_sellable_active_without_stock(data):
    product = get_product(data, 96)
    assert product["status"] == "active" and product["stock_quantity"] == 0
    assert not is_sellable(product)


def test_product_136_not_sellable_discontinued_with_stock(data):
    product = get_product(data, 136)
    assert product["status"] == "discontinued" and product["stock_quantity"] > 0
    assert not is_sellable(product)


def test_regular_product_is_sellable(data):
    assert is_sellable(get_product(data, 81))


def test_brand_mismatch_is_flagged_but_product_kept(data):
    product = get_product(data, 135)  # "Music Man Bass 1X" described as Fender Jazz Bass
    assert product is not None
    assert not product["description_reliable"]
    assert "Fender" in product["description_issue"]


def test_consistent_descriptions_stay_reliable(data):
    for pid in (81, 134, 138, 141, 143):  # 134: Fender named in a Fender description
        assert get_product(data, pid)["description_reliable"], pid


def test_quality_report_contents(data):
    report = data_quality_report(data)
    assert set(report["active_out_of_stock"]["product_id"]) == {96}
    assert set(report["discontinued_with_stock"]["product_id"]) == {136}
    assert "bruno.martins@jmail.com" in set(report["duplicated_customer_emails"]["email"])
    assert set(report["order_total_mismatches"]["order_id"]) == {3, 20}
    assert set(report["installment_rule_violations"]["order_id"]) == {9, 16, 18}
    unreleased = report["orders_with_unreleased_products"]
    assert set(unreleased["order_id"]) == {3, 14}
    assert set(unreleased["product_id"]) == {130}


def test_highest_discount_wins_when_two_promotions_are_active(data):
    extra = pd.DataFrame([{"promotion_id": 999, "product_id": 127, "discount_percent": 25,
                           "description": "Teste", "is_active": 1}])
    patched = replace(data, promotions=pd.concat([data.promotions, extra], ignore_index=True))
    assert active_promotion(patched, 127)["discount_percent"] == 25
