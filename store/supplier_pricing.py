from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone


MINIMUM_DATA_MARGIN = Decimal("30.00")
# Standard local Paystack funding reaches its highest effective rate at ₦2,500.
WALLET_FUNDING_FEE_RATE = Decimal("0.055")
# Reserve for the supplier's fixed N30 top-up fee when funding N1,000 at a time.
SUPPLIER_FUNDING_FEE_RATE = Decimal("0.03")


def estimated_data_margin(plan, cost, payment_method="wallet"):
    price = plan.selling_price
    if price is None:
        return None
    spread = price - cost
    cashback = plan.reward_amount
    if payment_method == "card":
        fee = min(Decimal("2000"), price * Decimal("0.015") + (100 if price >= 2500 else 0))
    else:
        fee = price * WALLET_FUNDING_FEE_RATE
    supplier_funding = (cost * SUPPLIER_FUNDING_FEE_RATE).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    return spread - cashback - fee.quantize(Decimal(".01"), rounding=ROUND_HALF_UP) - supplier_funding


def data_quote_allows_checkout(plan, payment_method="wallet"):
    quote = plan.supplier_quotes.filter(
        vendor_id=plan.provider.vendor_id,
        external_id=str(plan.vendor_bundle_id),
        available=True,
        approved=True,
        checked_at__gte=timezone.now() - timedelta(hours=24),
    ).first()
    return quote is not None and estimated_data_margin(plan, quote.cost, payment_method) >= MINIMUM_DATA_MARGIN
