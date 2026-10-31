from decimal import Decimal

import pytest

from emporio_agent.data import active_promotion, get_product
from emporio_agent.pricing import final_price, max_installments, pix_price

PRODUCT = {"product_id": 1, "price_brl": 1000.0}
ACTIVE = {"product_id": 1, "discount_percent": 20, "description": "Black Friday", "is_active": 1}
INACTIVE = {**ACTIVE, "is_active": 0}


def test_active_promotion_applies_and_keeps_original_price():
    quote = final_price(PRODUCT, ACTIVE)
    assert quote.original_price == Decimal("1000.00")
    assert quote.discount_percent == Decimal("20")
    assert quote.final_price == Decimal("800.00")


def test_inactive_promotion_is_ignored():
    quote = final_price(PRODUCT, INACTIVE)
    assert quote.discount_percent == 0
    assert quote.final_price == Decimal("1000.00")


def test_promotion_for_another_product_is_ignored():
    assert final_price(PRODUCT, {**ACTIVE, "product_id": 2}).final_price == Decimal("1000.00")


def test_product_with_only_inactive_promotions_has_no_discount(data):
    # Product 96 has two inactive promos (18% and 40%) in promotions.csv.
    assert active_promotion(data, 96) is None
    assert final_price(get_product(data, 96), None).final_price == Decimal("799.90")


def test_real_active_promotion(data):
    product = get_product(data, 127)
    quote = final_price(product, active_promotion(data, 127))
    assert (quote.original_price, quote.discount_percent, quote.final_price) == (
        Decimal("359.00"), Decimal("10"), Decimal("323.10"))


def test_pix_discount_without_promotion():
    quote = pix_price(PRODUCT, None)
    assert quote.discount_percent == Decimal("5")
    assert quote.final_price == Decimal("950.00")


def test_pix_discount_ignores_inactive_promotion():
    assert pix_price(PRODUCT, INACTIVE).final_price == Decimal("950.00")


def test_pix_does_not_stack_with_promotion():
    quote = pix_price(PRODUCT, ACTIVE)
    assert quote.discount_percent == Decimal("20")
    assert quote.final_price == Decimal("800.00")


def test_pix_rounds_half_up_to_cents():
    assert pix_price({"product_id": 81, "price_brl": 599.9}).final_price == Decimal("569.91")


@pytest.mark.parametrize("amount, expected", [
    (49.99, 1),
    (99.99, 1),
    (100, 2),       # 2 x 50
    (149.99, 2),
    (150, 3),       # 3 x 50
    (319.99, 3),    # 4x would be 79.99 < 80
    (320, 4),       # 4 x 80
    (479.99, 5),
    (480, 6),       # 6 x 80
    (699.99, 6),    # 7x would be 99.99 < 100
    (700, 7),       # 7 x 100
    (1199.99, 11),
    (1200, 12),     # 12 x 100
    (50000, 12),    # never above 12x
])
def test_max_installments_tier_boundaries(amount, expected):
    assert max_installments(amount) == expected


@pytest.mark.parametrize("amount", [0, -10])
def test_max_installments_rejects_non_positive(amount):
    with pytest.raises(ValueError):
        max_installments(amount)
