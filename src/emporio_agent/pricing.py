"""Pure pricing rules (manual sections 3 and 6.2).

All money math uses Decimal and rounds half-up to cents. Products and
promotions are any mapping with the CSV column names (dict or pandas Series).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

PIX_DISCOUNT_PERCENT = Decimal("5")
MAX_INSTALLMENTS = 12

# (max installments in tier, minimum installment value) — manual section 3.1
INSTALLMENT_TIERS = (
    (3, Decimal("50")),
    (6, Decimal("80")),
    (12, Decimal("100")),
)


@dataclass(frozen=True)
class PriceQuote:
    original_price: Decimal
    discount_percent: Decimal
    final_price: Decimal
    promotion: str | None = None

    @property
    def has_discount(self) -> bool:
        return self.discount_percent > 0


def _money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _apply_discount(price: Decimal, percent: Decimal) -> Decimal:
    return _money(price * (Decimal(100) - percent) / Decimal(100))


def is_promotion_active(promo: Mapping | None) -> bool:
    return promo is not None and int(promo["is_active"]) == 1


def final_price(product: Mapping, active_promo: Mapping | None = None) -> PriceQuote:
    """Table price with the promotion applied, if it is active and for this product."""
    original = _money(product["price_brl"])
    if not is_promotion_active(active_promo) or int(active_promo["product_id"]) != int(product["product_id"]):
        return PriceQuote(original, Decimal(0), original)

    percent = Decimal(str(active_promo["discount_percent"]))
    return PriceQuote(original, percent, _apply_discount(original, percent), str(active_promo["description"]))


def pix_price(product: Mapping, active_promo: Mapping | None = None) -> PriceQuote:
    """PIX price: 5% off the table price only when no promotion applies (no stacking)."""
    quote = final_price(product, active_promo)
    if quote.has_discount:
        return quote
    return PriceQuote(quote.original_price, PIX_DISCOUNT_PERCENT,
                      _apply_discount(quote.original_price, PIX_DISCOUNT_PERCENT), "PIX")


def min_installment_value(installments: int) -> Decimal:
    for tier_max, minimum in INSTALLMENT_TIERS:
        if installments <= tier_max:
            return minimum
    raise ValueError(f"At most {MAX_INSTALLMENTS} installments are allowed")


def max_installments(amount: Decimal | float | int | str) -> int:
    """Largest interest-free installment count whose installment respects the tier minimum.

    Amounts too small for any split (below R$ 100 for 2x) are paid in 1x.
    """
    amount = _money(amount)
    if amount <= 0:
        raise ValueError("Amount must be positive")
    for n in range(MAX_INSTALLMENTS, 1, -1):
        if amount / n >= min_installment_value(n):
            return n
    return 1


def installment_value(amount: Decimal | float | int | str, installments: int) -> Decimal:
    return _money(_money(amount) / installments)
