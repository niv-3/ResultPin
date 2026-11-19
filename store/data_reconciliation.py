"""Read supplier history; never repeat a purchase to discover its outcome."""
import logging
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import AirtimeTransaction, User, WalletTransaction

logger = logging.getLogger("payvict.delivery")
DATA_TIMEOUT = (3, 15)


def data_response(order, response):
    """Retain the supplier reference and treat unknown responses as pending."""
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = None
    if not isinstance(payload, dict):
        logger.warning("Data response reference=%s result=unreadable http=%s", order.reference, response.status_code)
        return {"status": "pending"}
    ref = payload.get("reference") or payload.get("tx_ref")
    if isinstance(ref, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", ref):
        order.supplier_reference = ref
        order.save(update_fields=["supplier_reference"])
    status = str(payload.get("status", "")).lower()
    if 200 <= response.status_code < 300 and status in ("true", "success"):
        result = "success"
    elif response.status_code < 500 and status in ("false", "failed", "refunded"):
        result = "failed"
    else:
        result = "pending"
    logger.warning("Data response reference=%s result=%s http=%s", order.reference, result, response.status_code)
    return {"status": result}


def phone_key(value):
    digits = re.sub(r"\D", "", str(value))
    return "0" + digits[3:] if digits.startswith("234") and len(digits) == 13 else digits


def matches(order, row):
    if not isinstance(row, dict) or not order.service_plan:
        return False
    try:
        timestamp = parse_datetime(row.get("timein", ""))
        if not timestamp or timezone.is_naive(timestamp):
            return False
        cost = order.supplier_cost if order.supplier_cost is not None else order.service_plan.cost_price
        if Decimal(str(row.get("amount"))) != cost:
            return False
    except (ValueError, TypeError, InvalidOperation):
        return False
    if abs((timestamp - order.created_at).total_seconds()) > 60:
        return False
    if phone_key(row.get("recipient", "")) != phone_key(order.phone):
        return False
    name = order.service_plan.name
    size = re.search(r"\d+(?:\.\d+)?\s*(?:GB|MB)", name, re.I)
    item = re.sub(r"\s+", "", str(row.get("item", ""))).lower()
    network = order.service_plan.provider.name.lower()
    return bool(size and item == re.sub(r"\s+", "", size.group()).lower() + network)


def reconcile_cheapdata(user_id=None):
    orders = AirtimeTransaction.objects.filter(
        payment_method="wallet", status="pending", user__isnull=False,
        created_at__lte=timezone.now() - timedelta(minutes=2),
    ).filter(supplier_adapter__in=("", "cheapdata"))
    if user_id is not None:
        orders = orders.filter(user_id=user_id)
    orders = list(orders.select_related("service_plan__provider")[:25])
    if not orders or not settings.CHEAPDATAHUB_API_KEY:
        return 0
    try:
        response = requests.get("https://www.cheapdatahub.ng/api/v1/resellers/transactions/",
            headers={"Authorization": f"Bearer {settings.CHEAPDATAHUB_API_KEY}"},
            timeout=(3, 5), allow_redirects=False)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return 0
    except (requests.RequestException, ValueError):
        logger.warning("Data reconciliation unavailable")
        return 0
    settled = 0
    for order in orders:
        candidates = [r for r in rows if matches(order, r) and (
            not order.supplier_reference or r.get("tx_ref") == order.supplier_reference)]
        if len(candidates) != 1:
            continue
        row = candidates[0]
        ref = row.get("tx_ref")
        if not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", ref):
            continue
        # Without an exact returned reference, reject any competing local order.
        peers = AirtimeTransaction.objects.filter(
            created_at__range=(order.created_at - timedelta(seconds=120), order.created_at + timedelta(seconds=120)),
        ).exclude(pk=order.pk).select_related("service_plan__provider")
        if any(peer.supplier_reference == ref or (not order.supplier_reference and matches(peer, row)) for peer in peers):
            continue
        refunded = row.get("category") == "Failed - Refunded" and row.get("completed") is False
        success = row.get("category") == "Successful" and row.get("completed") is True
        if not refunded and not success:
            continue
        with transaction.atomic():
            # Same lock order as checkout; credit and order status commit together.
            user = User.objects.select_for_update().get(pk=order.user_id)
            locked = AirtimeTransaction.objects.select_for_update().get(pk=order.pk)
            if locked.status != "pending":
                continue
            debit = WalletTransaction.objects.filter(user=user, reference=locked.reference,
                amount=locked.amount_paid, transaction_type="debit", status="success").exists()
            if not debit:
                continue
            refund_ref = f"REFUND-{locked.reference}"
            if refunded:
                credit, _ = WalletTransaction.objects.get_or_create(reference=refund_ref, defaults={
                    "user": user, "amount": locked.amount_paid, "transaction_type": "credit",
                    "status": "success", "source": "data_refund",
                    "description": "Refund for supplier-confirmed failed data purchase",
                })
                if (credit.user_id != user.pk or credit.amount != locked.amount_paid or
                        credit.transaction_type != "credit" or credit.status != "success"):
                    continue
                locked.status = "failed"
            else:
                # A manually refunded order must never also receive cashback.
                if WalletTransaction.objects.filter(reference=refund_ref).exists():
                    continue
                reward = locked.cashback_snapshot if locked.cashback_snapshot is not None else locked.service_plan.reward_amount
                if reward:
                    WalletTransaction.objects.get_or_create(reference=f"REWARD-{locked.reference}", defaults={
                        "user": user, "amount": reward, "transaction_type": "credit", "status": "success",
                        "source": "cashback_reward", "description": "Cashback reward for data purchase",
                    })
                locked.status = "success"
            locked.supplier_reference = ref
            locked.save(update_fields=["status", "supplier_reference"])
            settled += 1
            logger.warning("Data reconciliation reference=%s result=%s", locked.reference, locked.status)
    return settled
