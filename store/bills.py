import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.cache import never_cache

from .models import CableTransaction, ElectricityTransaction, ExamTransaction, Product, ServicePlan, ServiceProvider, User


TV_CATEGORY_SLUGS = ("tv", "cable", "dstv", "cable-tv")

EXAM_SERVICES = {"waecdirect": "waec", "utme-mock": "jamb", "utme-no-mock": "jamb"}

BILL_MODELS = {"cable": CableTransaction, "electricity": ElectricityTransaction, "education": ExamTransaction}


def vtpass_enabled():
    return all((settings.VTPASS_BILLS_ENABLED, settings.VTPASS_API_KEY, settings.VTPASS_SECRET_KEY))


def vtpass_post(endpoint, payload):
    base = "https://sandbox.vtpass.com/api" if settings.VTPASS_TEST_MODE else "https://vtpass.com/api"
    try:
        response = requests.post(
            f"{base}/{endpoint}",
            json=payload,
            headers={"api-key": settings.VTPASS_API_KEY, "secret-key": settings.VTPASS_SECRET_KEY},
            timeout=25,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def variation_price_available(service_id, variation, amount):
    base = "https://sandbox.vtpass.com/api" if settings.VTPASS_TEST_MODE else "https://vtpass.com/api"
    try:
        response = requests.get(
            f"{base}/service-variations", params={"serviceID": service_id}, timeout=10,
            headers={"api-key": settings.VTPASS_API_KEY, "public-key": settings.VTPASS_PUBLIC_KEY},
        )
        response.raise_for_status()
        for option in response.json()["content"]["variations"]:
            if option["variation_code"] == variation:
                price = Decimal(option["variation_amount"])
                return amount >= price if service_id == "waec" else amount == price
    except (requests.RequestException, ValueError, KeyError, TypeError, InvalidOperation):
        return False
    return False


def available_options(kind):
    if kind == "education":
        return Product.objects.filter(is_active=True, vendor_product_id__in=EXAM_SERVICES, sell_price__gt=0)
    providers = ServiceProvider.objects.filter(
        is_active=True, category__is_active=True,
    ).exclude(vtpass_service_id="")
    if kind == "electricity":
        electricity = providers.filter(category__slug="electricity")
        if not settings.VTPASS_TEST_MODE:
            electricity = electricity.exclude(vtpass_service_id="kano-electric")
        return electricity
    return ServicePlan.objects.filter(
        is_active=True, provider__in=providers.filter(category__slug__in=TV_CATEGORY_SLUGS),
        selling_price__gt=0,
    ).exclude(vtpass_variation_code="").select_related("provider")


@login_required
@never_cache
def dashboard(request, kind):
    options = available_options(kind) if vtpass_enabled() else []
    if kind == "cable":
        options = [{"id": plan.pk, "provider": plan.provider.name, "provider_id": plan.provider_id,
                    "total": plan.selling_price, "package_amount": plan.market_price or plan.selling_price,
                    "fee": plan.selling_price - (plan.market_price or plan.selling_price),
                    "label": f"{plan.name} — total ₦{plan.selling_price:,.2f}"}
                   for plan in options.select_related("provider").order_by("provider__order", "provider__name", "selling_price", "pk")]
    elif kind == "education":
        options = options.order_by("vendor_product_id", "pk") if vtpass_enabled() else []
    else:
        options = [{"id": provider.pk, "label": provider.name + (
            " (postpaid only)" if not settings.VTPASS_TEST_MODE and provider.vtpass_service_id == "aba-electric" else ""
        )} for provider in options]
    reference = datetime.now(ZoneInfo("Africa/Lagos")).strftime("%Y%m%d%H%M") + uuid4().hex[:12]
    checkout = signing.dumps([request.user.pk, kind, reference], salt="bill-checkout")
    template = "store/education_checkout.html" if kind == "education" else "store/bill_checkout.html"
    return render(request, template, {
        "kind": kind, "options": options, "checkout": checkout,
    })


def settle_bill(bill, response):
    content = response.get("content")
    provider_txn = content.get("transactions") if isinstance(content, dict) else None
    provider_status = provider_txn.get("status") if isinstance(provider_txn, dict) else None
    code = response.get("code")
    delivered = code in ("000", "001") and provider_status == "delivered"
    rejected = code in ("010", "011", "012", "013", "016", "017", "091") or (
        code in ("000", "001") and provider_status in ("failed", "reversed")
    )
    token = ""
    awaiting_token = False
    if isinstance(bill, ElectricityTransaction) and bill.meter_type == "prepaid":
        token = str(response.get("Token") or response.get("token") or response.get("purchased_code") or "")
        token = token.split(":")[-1].strip()
        awaiting_token = delivered and (not token or len(token) > 100)
        delivered = delivered and not awaiting_token
    serial = pin = ""
    if isinstance(bill, ExamTransaction):
        cards = response.get("cards")
        card = cards[0] if isinstance(cards, list) and cards and isinstance(cards[0], dict) else {}
        serial = str(card.get("Serial") or "")
        pin = str(card.get("Pin") or "")
        if EXAM_SERVICES.get(bill.product.vendor_product_id) == "jamb":
            match = re.fullmatch(r"(?:pin\s*:\s*)?([0-9]+)", str(response.get("Pin") or response.get("purchased_code") or "").strip(), re.I)
            pin = match.group(1) if match else ""
            delivered = delivered and 0 < len(pin) <= 100
        else:
            if not serial or not pin:
                match = re.fullmatch(
                    r"Serial\s+No\s*:\s*([A-Za-z0-9-]+)\s*,\s*pin\s*:\s*([0-9]+)",
                    str(response.get("purchased_code") or "").strip(), re.I,
                )
                if match:
                    serial, pin = match.groups()
            delivered = delivered and 0 < len(serial) <= 100 and 0 < len(pin) <= 100
    if not delivered and not rejected and not awaiting_token:
        return
    with transaction.atomic():
        locked = type(bill).objects.select_for_update().get(pk=bill.pk)
        if locked.status not in ("pending", "token_pending"):
            return
        if locked.status == "token_pending" and rejected:
            # A later conflicting response needs reconciliation before refunding.
            return
        locked.status = "success" if delivered else "token_pending" if awaiting_token else "failed"
        fields = ["status"]
        if delivered and token:
            locked.token = token
            fields.append("token")
        if delivered and pin:
            locked.serial = serial
            locked.pin = pin
            fields.extend(["serial", "pin"])
        if rejected and not delivered:
            locked.user.credit_wallet(
                locked.amount_paid, source="bill_refund", reference=f"REFUND-{locked.reference}",
                description="Refund for unsuccessful bill payment",
            )
        locked.save(update_fields=fields)


@login_required
@require_POST
def purchase(request, kind):
    page = {"cable": "tv_dashboard", "electricity": "electricity_dashboard", "education": "education_dashboard"}[kind]
    if not vtpass_enabled():
        messages.error(request, "Bill payments are currently unavailable.")
        return redirect(page)
    try:
        owner, checkout_kind, request_id = signing.loads(
            request.POST.get("checkout", ""), salt="bill-checkout", max_age=3600,
        )
        selection = int(request.POST.get("selection", ""))
        if owner != request.user.pk or checkout_kind != kind:
            raise ValueError
    except (signing.BadSignature, ValueError):
        messages.error(request, "Your checkout expired or the selection is invalid. Please try again.")
        return redirect(page)
    if BILL_MODELS[kind].objects.filter(reference=request_id, user=request.user).exists():
        return redirect("bill_receipt", kind=kind, reference=request_id)
    option = get_object_or_404(available_options(kind), pk=selection)
    number = request.POST.get("account_number", "").strip()
    phone = request.POST.get("phone", "").strip()
    if not re.fullmatch(r"0[0-9]{10}", phone) or (kind != "education" and not re.fullmatch(r"[0-9]{8,20}", number)):
        messages.error(request, "Enter a valid account number and an 11-digit Nigerian phone number.")
        return redirect(page)
    if kind == "education":
        amount = option.sell_price
        variation = option.vendor_product_id
        verify = {}
        details = {"product": option}
        service_id = EXAM_SERVICES[variation]
        if service_id == "jamb":
            if not re.fullmatch(r"[0-9]{10}", number):
                messages.error(request, "Enter your 10-digit JAMB Profile ID.")
                return redirect(page)
            verify = {"serviceID": service_id, "billersCode": number, "type": variation}
        extra = {"serviceID": service_id, "quantity": 1}
    elif kind == "cable":
        amount = option.selling_price
        package_amount = option.market_price or amount
        try:
            agreed_total = Decimal(request.POST.get("expected_total", ""))
        except InvalidOperation:
            agreed_total = None
        if agreed_total != amount or package_amount <= 0 or amount < package_amount:
            messages.error(request, "Review the current package price and service fee before paying.")
            return redirect(page)
        variation = option.vtpass_variation_code
        verify = {"serviceID": option.provider.vtpass_service_id, "billersCode": number}
        details = {"service_plan": option, "cardnumber": number,
                   "package_amount": package_amount, "service_fee": amount - package_amount}
        extra = {"subscription_type": "change"}
    else:
        variation = request.POST.get("meter_type")
        if not settings.VTPASS_TEST_MODE and option.vtpass_service_id == "aba-electric" and variation == "prepaid":
            messages.error(request, "Aba prepaid token delivery is awaiting confirmation. Only postpaid payments are available for Aba.")
            return redirect(page)
        try:
            amount = Decimal(request.POST.get("amount", ""))
        except InvalidOperation:
            amount = Decimal("NaN")
        if (variation not in ("prepaid", "postpaid") or not amount.is_finite()
                or not 100 <= amount <= 100000 or amount != amount.quantize(Decimal("0.01"))):
            messages.error(request, "Choose a meter type and enter an amount from ₦100 to ₦100,000.")
            return redirect(page)
        verify = {"serviceID": option.vtpass_service_id, "billersCode": number, "type": variation}
        details = {"meter_number": number, "meter_type": variation, "disco_id": option.pk}
        extra = {}
    if kind == "cable" and not variation_price_available(option.provider.vtpass_service_id, variation, package_amount):
        messages.error(request, "This TV package or price is currently unavailable. Please try again later.")
        return redirect(page)
    if kind == "education" and not variation_price_available(service_id, variation, amount):
        messages.error(request, "This exam product or price is currently unavailable.")
        return redirect(page)
    if verify:
        verified = vtpass_post("merchant-verify", verify)
        content = verified.get("content")
        account_verified = isinstance(content, dict) and bool(content.get("Customer_Name"))
        # Jos can verify a meter without returning the customer's name.
        if kind == "electricity" and verify["serviceID"] == "jos-electric" and isinstance(content, dict):
            account_verified = account_verified or (
                str(content.get("MeterNumber", "")) == number
                and str(content.get("Meter_Type", "")).lower() == variation
                and content.get("WrongBillersCode") in (None, False)
            )
        if verified.get("code") != "000" or not account_verified:
            messages.error(request, "We could not verify that account. Check the number and selected provider.")
            return redirect(page)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if BILL_MODELS[kind].objects.filter(reference=request_id, user=user).exists():
            return redirect("bill_receipt", kind=kind, reference=request_id)
        if kind == "electricity" and variation == "prepaid":
            previous = ElectricityTransaction.objects.filter(
                user=user, disco_id=option.pk, meter_number=number, meter_type="prepaid",
                status__in=("pending", "token_pending"),
            ).order_by("-created_at").first()
            if previous:
                return redirect("bill_receipt", kind=kind, reference=previous.reference)
        if user.wallet_balance < amount:
            messages.error(request, "Your wallet balance is too low for this payment.")
            return redirect(page)
        if kind != "education":
            details["phone"] = phone
        bill = BILL_MODELS[kind].objects.create(
            user=user, reference=request_id, amount_paid=amount, status="pending", **details,
        )
        user.debit_wallet(amount, source=f"{kind}_purchase", reference=request_id, description=option.name if kind == "education" else "Bill payment")
    payload = {
        "variation_code": variation,
        "request_id": request_id, "amount": float(amount), "phone": phone, **extra,
    }
    if kind == "cable":
        payload["amount"] = float(package_amount)
    if verify:
        payload.update(serviceID=verify["serviceID"], billersCode=number)
    if kind == "cable" and payload["serviceID"] == "startimes":
        # StarTimes uses the bouquet price when amount is omitted.
        del payload["amount"]
        del payload["subscription_type"]
    settle_bill(bill, vtpass_post("pay", payload))
    return redirect("bill_receipt", kind=kind, reference=request_id)


@login_required
@require_http_methods(["GET", "POST"])
def receipt(request, kind, reference):
    if kind not in BILL_MODELS:
        raise Http404
    bill = get_object_or_404(BILL_MODELS[kind], reference=reference, user=request.user)
    if request.method == "POST":
        if bill.status in ("pending", "token_pending") and vtpass_enabled():
            settle_bill(bill, vtpass_post("requery", {"request_id": bill.reference}))
        return redirect("bill_receipt", kind=kind, reference=reference)
    return render(request, "store/bill_receipt.html", {
        "bill": bill, "kind": kind,
        "is_jamb": kind == "education" and EXAM_SERVICES.get(bill.product.vendor_product_id) == "jamb",
    })
