import json

import pytest

from emporio_agent.tools import (
    get_order_status, get_product, list_categories, normalize_phone, search_products,
)


def _roundtrip(result: dict) -> dict:
    """Every tool output must survive JSON serialization unchanged."""
    return json.loads(json.dumps(result))


# --- list_categories ---------------------------------------------------------

def test_wind_and_orchestral_categories_have_zero_sellable():
    counts = {c["name"]: c["sellable_products"] for c in list_categories()["categories"]}
    assert counts["Instrumentos de Sopro (Madeiras)"] == 0
    assert counts["Instrumentos de Sopro (Metais)"] == 0
    assert counts["Cordas Orquestrais"] == 0
    # 35 violões in the catalog minus 96 (no stock) and 113 (discontinued)
    assert counts["Violões"] == 33


def test_list_categories_is_json_serializable():
    _roundtrip(list_categories())


# --- search_products -----------------------------------------------------------

def test_violoes_up_to_1000_are_sellable_and_sorted():
    result = search_products(category="violões", max_price=1000)
    products = result["products"]
    prices = [p["final_price_brl"] for p in products]

    assert products and prices == sorted(prices)
    assert all(p["final_price_brl"] <= 1000 for p in products)
    assert all(p["category"] == "Violões" for p in products)
    ids = {p["id"] for p in products}
    assert 96 not in ids and 113 not in ids
    assert result["returned"] == len(products) <= 10
    assert result["total"] >= result["returned"]


def test_search_reports_total_beyond_limit():
    result = search_products(category="Violões")
    assert result["total"] == 33
    assert result["returned"] == 10


def test_search_item_has_full_price_breakdown():
    item = next(p for p in search_products(query="KAL-700T")["products"] if p["id"] == 127)
    assert item["original_price_brl"] == 359.0
    assert item["promotion_discount_percent"] == 10.0
    assert item["final_price_brl"] == 323.1
    assert item["pix_price_brl"] == 323.1  # PIX does not stack with the promotion
    assert item["max_installments"] == 4
    assert "description" in item


def test_unreliable_description_is_omitted():
    item = next(p for p in search_products(query="Music Man Bass 1X")["products"] if p["id"] == 135)
    assert "description" not in item
    assert item["specs"]["strings"] == "4"


def test_search_by_wind_category_is_empty():
    result = search_products(category="sopro")
    assert result["total"] == 0 and "error" not in result


def test_unknown_category_returns_error():
    result = search_products(category="pedais")
    assert result["error"] == "unknown_category"
    assert result["products"] == []


def test_query_with_stopwords_and_extra_words_still_finds_products():
    # Regression: AND matching returned 0 here although beginner guitars are in stock.
    assert search_products(query="violão bom para iniciante")["total"] > 0


def test_stopwords_do_not_change_results():
    assert search_products(query="um violão iniciante")["total"] == search_products(query="violão iniciante")["total"]


@pytest.mark.parametrize("query", ["xyz inexistente", "para um de"])
def test_query_without_matching_terms_returns_nothing(query):
    result = search_products(query=query)
    assert result["total"] == 0 and result["products"] == []


def test_query_ranks_by_matched_terms_then_price():
    products = search_products(query="violão iniciante")["products"]
    both = [p for p in products
            if all(w in p.get("description", "").lower() for w in ("violão", "iniciante"))]
    assert both
    # products matching both terms come before those matching only "violão"
    assert products[:len(both)] == both
    prices = [p["final_price_brl"] for p in both]
    assert prices == sorted(prices)


def test_full_match_total_and_matched_terms():
    result = search_products(query="violão iniciante")
    assert result["full_match_total"] == 3
    ukulele = next(p for p in result["products"] if p["id"] == 116)
    assert ukulele["matched_terms"] == ["iniciante"]
    assert result["products"][0]["matched_terms"] == ["violao", "iniciante"]


def test_search_is_json_serializable():
    _roundtrip(search_products(category="Guitarras"))


# --- get_product ---------------------------------------------------------------

@pytest.mark.parametrize("query", ["takamine gd20", "TAKAMINE GD20", "Takamine  GD-20", 95, "95"])
def test_get_product_finds_takamine_gd20(query):
    result = get_product(query)
    assert result["availability"] == "available"
    assert result["product"]["id"] == 95


def test_get_product_tolerates_typos():
    result = get_product("takamini gd20")
    assert result["product"]["id"] == 95


def test_product_96_out_of_stock_with_alternatives():
    result = get_product(96)
    assert result["availability"] == "out_of_stock"
    assert "final_price_brl" not in result["product"]
    alternatives = result["alternatives"]
    assert 1 <= len(alternatives) <= 3
    assert all(a["category"] == "Violões" and a["id"] != 96 for a in alternatives)
    # closest in price to R$ 799.90 come first
    gaps = [abs(a["final_price_brl"] - 799.9) for a in alternatives]
    assert gaps == sorted(gaps)


@pytest.mark.parametrize("query", [96, "Giannini GF-3D"])
def test_alternatives_keep_string_type(query):
    # Regression: the steel-string 96 got the nylon Yamaha C70 (82) as an alternative.
    alternatives = get_product(query)["alternatives"]
    assert len(alternatives) == 3
    assert all(a["specs"]["strings"] == "steel" for a in alternatives)
    assert 82 not in {a["id"] for a in alternatives}


@pytest.mark.parametrize("product_id, availability", [
    (136, "discontinued"),  # discontinued even though it has stock
    (113, "discontinued"),
    (130, "coming_soon"),
])
def test_unavailable_statuses(product_id, availability):
    assert get_product(product_id)["availability"] == availability


def test_ambiguous_name_returns_candidates():
    result = get_product("Martin D-28")
    assert result["availability"] == "ambiguous"
    assert {c["id"] for c in result["candidates"]} == {93, 108}


@pytest.mark.parametrize("query", ["xyz", "saxofone", 9999])
def test_not_found(query):
    assert get_product(query)["availability"] == "not_found"


def test_get_product_is_json_serializable():
    for query in (95, 96, "Martin D-28", "xyz"):
        _roundtrip(get_product(query))


# --- get_order_status ----------------------------------------------------------

def test_wrong_contact_and_missing_order_return_same_error():
    wrong_contact = get_order_status(2, "someone.else@jmail.com")
    missing_order = get_order_status(999, "thiago.barbosa@jmail.com")
    assert wrong_contact == missing_order
    assert wrong_contact["found"] is False


@pytest.mark.parametrize("contact", [
    "thiago.barbosa@jmail.com",
    "  Thiago.Barbosa@JMAIL.com ",
    "(67) 98321-6543",
    "67983216543",
    "+55 67 98321-6543",
])
def test_order_2_opens_with_customer_7_contact(contact):
    result = get_order_status(2, contact)
    assert result["found"] is True
    assert result["order_id"] == 2
    assert result["status"] == "delivered"
    assert result["items"] == [{"product_name": "Taylor 110e Dreadnought Natural", "quantity": 1}]
    assert result["tracking_code"] == "BRCX9876543BR"
    assert result["estimated_delivery"] == "2025-11-15"


def test_order_response_has_no_personal_data():
    result = _roundtrip(get_order_status(2, "thiago.barbosa@jmail.com"))
    serialized = json.dumps(result)
    assert "thiago" not in serialized.lower()
    assert "98321" not in serialized
    assert "customer_id" not in result


def test_pending_order_has_null_tracking():
    result = get_order_status(13, "fernanda.ribeiro@coldmail.com")
    assert result["status"] == "pending"
    assert result["tracking_code"] is None and result["estimated_delivery"] is None


def test_duplicated_email_does_not_open_other_customers_orders():
    email = "bruno.martins@jmail.com"  # shared by customers 11 and 43
    # Order 10 belongs to customer 11, the e-mail is legitimately his.
    assert get_order_status(10, email)["found"] is True
    # It must not open orders from any other customer.
    assert get_order_status(2, email)["found"] is False
    assert get_order_status(3, email)["found"] is False
    # Customer 43's phone does not open customer 11's order.
    assert get_order_status(10, "(67) 99456-3456")["found"] is False


@pytest.mark.parametrize("order_id, contact", [("abc", "thiago.barbosa@jmail.com"), (2, ""), (2, "123")])
def test_invalid_inputs_return_generic_error(order_id, contact):
    assert get_order_status(order_id, contact) == get_order_status(999, "x@y.com")


def test_normalize_phone_strips_country_code():
    assert normalize_phone("+55 (67) 98321-6543") == normalize_phone("(67) 98321-6543") == "67983216543"
