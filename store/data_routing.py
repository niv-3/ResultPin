"""Select before charging; never resend an uncertain order to another supplier."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import requests
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import DataSupplier
from .supplier_pricing import MINIMUM_DATA_MARGIN, estimated_data_margin


def credentials_ready(adapter):
    if adapter == "cheapdata":
        return bool(settings.CHEAPDATAHUB_API_KEY)
    if adapter == "nellobyte":
        return bool(settings.NELLOBYTE_USER_ID and settings.NELLOBYTE_API_KEY)
    return False


def total_supplier_cost(quote):
    profile = quote.vendor.data_supplier
    return (quote.cost * (1 + profile.funding_fee_rate) + profile.purchase_fee).quantize(
        Decimal(".01"), rounding=ROUND_HALF_UP)


def select_data_quote(plan, payment_method="wallet"):
    now = timezone.now()
    candidates = plan.supplier_quotes.select_related("vendor__data_supplier").filter(
        available=True, approved=True, cost__gt=0,
        checked_at__gte=now - timedelta(hours=24), checked_at__lte=now,
        vendor__is_active=True, vendor__data_supplier__enabled=True,
        vendor__data_supplier__funded=True,
    ).filter(Q(vendor__data_supplier__paused_until__isnull=True) |
             Q(vendor__data_supplier__paused_until__lte=now))
    eligible = []
    for quote in candidates:
        profile = quote.vendor.data_supplier
        if not credentials_ready(profile.adapter):
            continue
        if profile.adapter == "nellobyte" and not quote.network_code:
            continue
        if not quote.external_id or not quote.external_id.isdecimal():
            continue
        margin = estimated_data_margin(plan, quote.cost, payment_method,
                                       supplier_total=total_supplier_cost(quote))
        if margin is not None and margin >= MINIMUM_DATA_MARGIN:
            eligible.append(quote)
    return min(eligible, key=lambda q: (total_supplier_cost(q), q.vendor.priority, q.pk), default=None)


def order_supplier_snapshot(plan, quote):
    return {
        "supplier_vendor_id": quote.vendor_id,
        "supplier_adapter": quote.vendor.data_supplier.adapter,
        "supplier_external_id": quote.external_id,
        "supplier_network_code": quote.network_code,
        "supplier_cost": quote.cost,
        "supplier_total_cost": total_supplier_cost(quote),
        # Honour the cashback shown to the buyer, regardless of internal routing.
        "cashback_snapshot": plan.reward_amount,
    }


def pending_delivery(order):
    DataSupplier.objects.filter(vendor_id=order.supplier_vendor_id).update(
        paused_until=timezone.now() + timedelta(minutes=2))
    return {"status": "pending"}


def vend_data(order):
    """Only a documented terminal result is success/failure; all ambiguity stays pending."""
    adapter = order.supplier_adapter
    if not credentials_ready(adapter):
        return {"status": "failed"}  # No request was sent.
    quote = order.service_plan.supplier_quotes.select_related("vendor__data_supplier").filter(
        vendor_id=order.supplier_vendor_id, external_id=order.supplier_external_id,
        network_code=order.supplier_network_code, approved=True, available=True,
        checked_at__gte=timezone.now() - timedelta(hours=24), checked_at__lte=timezone.now(),
        vendor__is_active=True, vendor__data_supplier__enabled=True,
        vendor__data_supplier__funded=True, vendor__data_supplier__adapter=adapter,
    ).first()
    if quote is None or quote.cost > order.supplier_cost or total_supplier_cost(quote) > order.supplier_total_cost:
        return {"status": "failed"}  # Changed or removed quote: no request, full refund.
    profile = quote.vendor.data_supplier
    if profile.paused_until and profile.paused_until > timezone.now():
        return {"status": "failed"}  # No request was sent.
    try:
        if adapter == "cheapdata":
            response = requests.post(
                "https://www.cheapdatahub.ng/api/v1/resellers/data/purchase/",
                headers={"Authorization": f"Bearer {settings.CHEAPDATAHUB_API_KEY}",
                         "Content-Type": "application/json", "Accept": "application/json"},
                json={"bundle_id": int(order.supplier_external_id), "phone_number": order.phone},
                timeout=30, allow_redirects=False,
            )
        elif adapter == "nellobyte":
            response = requests.get(
                "https://www.nellobytesystems.com/APIDatabundleV1.asp",
                params={"UserID": settings.NELLOBYTE_USER_ID, "APIKey": settings.NELLOBYTE_API_KEY,
                        "MobileNetwork": order.supplier_network_code,
                        "DataPlan": order.supplier_external_id, "MobileNumber": order.phone,
                        "RequestID": order.reference},
                timeout=30, allow_redirects=False,
            )
        else:
            return {"status": "failed"}
        if response.status_code >= 300:
            return pending_delivery(order)
        payload = response.json()
        if not isinstance(payload, dict):
            return pending_delivery(order)
    except (requests.RequestException, ValueError, TypeError):
        # Never log exception URLs: the legacy Nellobyte API puts credentials in the query.
        return pending_delivery(order)
    if adapter == "nellobyte":
        supplier_ref = str(payload.get("orderid", ""))[:100]
        if supplier_ref:
            order.supplier_reference = supplier_ref
            order.save(update_fields=["supplier_reference"])
        status = str(payload.get("status", "")).upper()
        if status == "ORDER_COMPLETED":
            return {"status": "success"}
        # Only explicit rejection before an order was accepted can be refunded here.
        if status in {"INVALID_CREDENTIALS", "MISSING_CREDENTIALS", "MISSING_USERID",
                      "MISSING_APIKEY", "MISSING_MOBILENETWORK", "MISSING_DATAPLAN",
                      "INVALID_DATAPLAN", "INVALID_RECIPIENT", "INSUFFICIENT_BALANCE"}:
            return {"status": "failed"}
        return pending_delivery(order)
    status = str(payload.get("status", "")).lower()
    if status in ("true", "success"):
        return {"status": "success"}
    if status in ("false", "failed"):
        return {"status": "failed"}
    return pending_delivery(order)
