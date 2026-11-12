import json
import uuid
import hmac
import hashlib
import requests
from decimal import Decimal, InvalidOperation
import re
import time
import random

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction, IntegrityError
from .authentication import normalize_phone
from django.http import Http404, JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from datetime import timedelta
from django.db.models import Sum
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError

User = get_user_model()

from .models import (
    FAQ,
    ServiceCategory,
    ServiceProvider,
    ServicePlan,
    AirtimeTransaction,
    WalletTransaction,
    Referral,
    BankAccount,
    BlogPost,
    Review,
    CableTransaction,
    ElectricityTransaction,
)

from .bills import BILL_MODELS, TV_CATEGORY_SLUGS
from .google_auth import google_enabled
from .paystack import initialize_paystack, verify_paystack
from .supplier_pricing import data_quote_allows_checkout

# views.py
def get_service_type_from_plan(plan):
    """
    Maps a ServicePlan's category slug to the internal service type string
    that the payment views expect ('airtime', 'data', 'cable', 'electricity').

    Returns None if invalid or missing data.
    """
    if not plan or not plan.provider or not plan.provider.category:
        print("get_service_type_from_plan: Missing plan/provider/category")
        return None

    # Normalize slug (remove case & whitespace issues)
    slug = (plan.provider.category.slug or "").lower().strip()

    mapping = {
        "airtime": "airtime",
        "internet-data": "data",
        "data": "data",                 # safety if slug changes later
        "tv": "cable",
        "cable": "cable",
        "electricity": "electricity",
        # Add future categories here, e.g.
        # "education": "education",
        # "betting": "betting",
    }

    service_type = mapping.get(slug)

    if service_type:
        return service_type

    # Warning with more context
    plan_info = f"ID {plan.id} ({plan.name})" if plan else "unknown plan"
    print(f"WARNING: Unknown category slug '{slug}' for plan {plan_info}")
    return None


# ==============================
# RESELLER API HELPERS
# ==============================
RESELLER_BASE_URL = "https://www.cheapdatahub.ng" 

RESELLER_HEADERS = {
    "Authorization": f"Bearer {settings.CHEAPDATAHUB_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# ==============================
# VIEWS
# ==============================
def home(request):
    categories = ServiceCategory.objects.filter(is_active=True).exclude(slug="insurance").order_by("order", "pk")
    tv_category = categories.filter(slug="cable-tv").first() or categories.filter(slug__in=TV_CATEGORY_SLUGS).first()
    services = [
        category for category in categories
        if category.slug not in TV_CATEGORY_SLUGS or category == tv_category
    ]

    return render(request, "store/home.html", {"services": services})

def faq_view(request):
    faq_list = FAQ.objects.all().order_by('id')  # ← safe option
    # Or if you have a date field:
    # faq_list = FAQ.objects.all().order_by('-created_at')
    return render(request, 'store/faq.html', {'faq_list': faq_list})

    
def confirm_wallet_topup(topup, payment):
    if (
        not isinstance(payment, dict)
        or payment.get("status") != "success"
        or payment.get("reference") != topup.reference
        or payment.get("currency") != "NGN"
        or type(payment.get("amount")) is not int
        or payment["amount"] != int(topup.amount * 100)
    ):
        return False

    updated = WalletTransaction.objects.filter(pk=topup.pk, status="pending").update(status="success")
    return bool(updated) or WalletTransaction.objects.filter(pk=topup.pk, status="success").exists()


@csrf_exempt
@require_POST
def paystack_webhook(request):
    signature = request.headers.get("x-paystack-signature", "")
    secret = settings.PAYSTACK_SECRET_KEY
    if not secret or not signature:
        return HttpResponse("Missing webhook credentials", status=400)

    computed = hmac.new(secret.encode(), request.body, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(computed, signature):
        return HttpResponse("Invalid signature", status=400)

    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return HttpResponse("Invalid JSON", status=400)

    if not isinstance(payload, dict):
        return HttpResponse("Invalid event", status=400)
    if payload.get("event") != "charge.success":
        return HttpResponse("Ignored event")

    payment = payload.get("data")
    reference = payment.get("reference") if isinstance(payment, dict) else None
    if isinstance(reference, str) and reference.startswith(("CARD-AIRTIME-", "CARD-DATA-")):
        order = card_service_orders().filter(reference=reference).first()
        if order and not complete_card_service_order(order, payment):
            return HttpResponse("Payment does not match service order", status=400)
        return HttpResponse("OK")

    if not isinstance(reference, str) or not reference.startswith("WALLET-"):
        return HttpResponse("Ignored reference")

    topup = WalletTransaction.objects.filter(
        reference=reference, transaction_type="credit", source="funding",
    ).first()
    if topup and not confirm_wallet_topup(topup, payment):
        return HttpResponse("Payment does not match wallet funding", status=400)
    return HttpResponse("OK")


@login_required
def wallet(request):
    user = request.user
    cutoff = timezone.now() - timedelta(days=7)
    history = list(user.wallet_transactions.filter(created_at__gte=cutoff))
    for entry in history:
        if entry.status != "success":
            entry.payment_status = entry.status
    debits = {txn.reference: txn for txn in history if txn.transaction_type == "debit"}
    for kind, model in BILL_MODELS.items():
        bills = model.objects.filter(user=user, reference__in=debits)
        for bill in bills:
            entry = debits[bill.reference]
            entry.receipt_url = reverse("bill_receipt", args=[kind, bill.reference])
            entry.payment_status = bill.status

    card_payments = AirtimeTransaction.objects.filter(
        user=user, payment_method="card", created_at__gte=cutoff,
    ).select_related("service_plan")
    for payment in card_payments:
        history.append({
            "created_at": payment.created_at,
            "description": payment.service_plan.name if payment.service_plan else "Service purchase",
            "transaction_type": "card",
            "amount": payment.amount_paid,
            "payment_status": payment.status,
        })

    def created_at(entry):
        return entry["created_at"] if isinstance(entry, dict) else entry.created_at

    history.sort(key=created_at, reverse=True)
    wallet_transactions = Paginator(history, 25).get_page(request.GET.get("page"))

    referral_earnings = (
        user.wallet_transactions.filter(
            source="referral",
            transaction_type="credit",
            status="success",
        )
        .aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )

    context = {
        "total_referrals": user.total_referrals,
        "referral_earnings": referral_earnings,
        "wallet_transactions": wallet_transactions,
        "withdrawals_enabled": settings.WALLET_WITHDRAWALS_ENABLED,
    }
    return render(request, "store/wallet.html", context)


@login_required
def wallet_fund(request):
    return render(
        request,
        "store/wallet_fund.html",
        {"paystack_public_key": settings.PAYSTACK_PUBLIC_KEY},
    )


@login_required
@require_POST
@csrf_protect
def wallet_fund_init(request):
    try:
        data = json.loads(request.body)
        amount = Decimal(str(data["amount"]))
        if not amount.is_finite() or not Decimal("100") <= amount <= Decimal("5000000"):
            raise ValueError
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueError
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return JsonResponse({"status": False, "message": "Enter an amount from ₦100 to ₦5,000,000 with up to two decimal places."})

    topup = WalletTransaction.objects.create(
        user=request.user, amount=amount, transaction_type="credit", source="funding",
        description="Wallet top-up", status="pending",
        reference=f"WALLET-{uuid.uuid4().hex.upper()}",
    )
    try:
        result = initialize_paystack(
            email=request.user.email,
            amount=int(amount * 100),
            reference=topup.reference,
            callback_url=request.build_absolute_uri(reverse("verify_wallet_funding")),
        )
        if result.get("status") is True:
            url = result["data"]["authorization_url"]
            if isinstance(url, str) and url:
                return JsonResponse({"status": True, "data": {"authorization_url": url}})
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        # A request can fail after Paystack accepts it. Retain the reference for settlement.
        pass
    return JsonResponse({"status": False, "message": "Could not open Paystack checkout. Please try again."})


@login_required
def verify_wallet_funding(request):
    reference = request.GET.get("reference", "")
    if not re.fullmatch(r"WALLET-[0-9A-F]{12,32}", reference):
        messages.error(request, "Invalid funding reference.")
        return redirect("wallet")

    funding = request.user.wallet_transactions.filter(transaction_type="credit", source="funding")
    topup = funding.filter(reference=reference).first()
    if topup and topup.status == "success":
        messages.info(request, "This top-up has already been credited.")
        return redirect("wallet")

    # In-flight checkouts created before pending top-ups were persisted.
    legacy = request.session.get("pending_wallet_fund")
    if topup is None and (not legacy or legacy.get("reference") != reference):
        messages.error(request, "Wallet top-up was not found.")
        return redirect("wallet")

    try:
        result = verify_paystack(reference)
        payment = result.get("data") if result.get("status") is True else None
        if topup is None and isinstance(payment, dict) and payment.get("status") == "success":
            topup, _ = WalletTransaction.objects.get_or_create(
                reference=reference,
                defaults={
                    "user": request.user, "amount": Decimal(legacy["amount"]),
                    "transaction_type": "credit", "source": "funding",
                    "description": "Wallet top-up", "status": "pending",
                },
            )
            if topup.user_id != request.user.pk or topup.transaction_type != "credit" or topup.source != "funding":
                topup = None
    except (requests.RequestException, ValueError, InvalidOperation, KeyError, TypeError, AttributeError):
        messages.info(request, "Could not verify this payment yet. Please check your wallet history shortly.")
        return redirect("wallet")

    if topup and confirm_wallet_topup(topup, payment):
        if legacy and legacy.get("reference") == reference:
            request.session.pop("pending_wallet_fund", None)
        messages.success(request, f"Wallet credited with ₦{topup.amount:,}!")
    else:
        messages.info(request, "This wallet payment has not been confirmed.")
    return redirect("wallet")


@login_required
def add_bank_account(request):
    if not settings.WALLET_WITHDRAWALS_ENABLED:
        raise Http404

    if request.method == "POST":
        account_number = request.POST.get("account_number")
        bank_code = request.POST.get("bank_code")

        if not account_number or not bank_code:
            return JsonResponse({"success": False, "message": "All fields required"})

        name = "Test Account" if settings.DEBUG else None

        if not settings.DEBUG:
            try:
                resolve = requests.get(
                    f"https://api.paystack.co/bank/resolve?account_number={account_number}&bank_code={bank_code}",
                    headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
                    timeout=10,
                ).json()
                if not resolve.get("status"):
                    return JsonResponse({"success": False, "message": "Invalid account details"})
                name = resolve["data"]["account_name"]
            except Exception:
                return JsonResponse({"success": False, "message": "Bank verification failed"})

        try:
            recipient = requests.post(
                "https://api.paystack.co/transferrecipient",
                json={
                    "type": "nuban",
                    "name": name,
                    "account_number": account_number,
                    "bank_code": bank_code,
                    "currency": "NGN",
                },
                headers={
                    "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            ).json()

            if not recipient.get("status"):
                return JsonResponse({"success": False, "message": "Failed to create recipient"})
        except Exception:
            return JsonResponse({"success": False, "message": "Recipient creation failed"})

        BankAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "bank_code": bank_code,
                "account_number": account_number,
                "account_name": name,
                "recipient_code": recipient["data"]["recipient_code"],
                "is_verified": True,
            },
        )

        return JsonResponse({"success": True, "account_name": name})

    banks = [
        {"code": "044", "name": "Access Bank"},
        {"code": "057", "name": "Zenith Bank"},
        {"code": "058", "name": "GTBank"},
        {"code": "050", "name": "Ecobank"},
    ]
    return render(request, "store/add_bank_account.html", {"banks": banks})


@login_required
def wallet_withdraw(request):
    if not settings.WALLET_WITHDRAWALS_ENABLED:
        raise Http404

    bank_account = getattr(request.user, "bank_account", None)

    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get("amount", "0"))
        except Exception:
            messages.error(request, "Invalid amount.")
            return redirect("wallet_withdraw")

        if amount < Decimal("100"):
            messages.error(request, "Minimum withdrawal is ₦100.")
            return redirect("wallet_withdraw")

        if request.user.wallet_balance < amount:
            messages.error(request, "Insufficient balance.")
            return redirect("wallet_withdraw")

        if not bank_account or not bank_account.recipient_code:
            messages.error(request, "No verified bank account found.")
            return redirect("wallet_withdraw")

        reference = f"WITHDRAW-{uuid.uuid4().hex[:12].upper()}"

        response = requests.post(
            "https://api.paystack.co/transfer",
            json={
                "source": "balance",
                "amount": int(amount * 100),
                "recipient": bank_account.recipient_code,
                "reference": reference,
                "reason": "Wallet withdrawal",
            },
            headers={
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=20,
        ).json()

        if not response.get("status"):
            messages.error(
                request,
                response.get("message", "Withdrawal failed."),
            )
            return redirect("wallet_withdraw")

        with transaction.atomic():
            WalletTransaction.objects.create(
                user=request.user,
                amount=amount,
                transaction_type="debit",
                source="withdrawal",
                status="success",
                reference=reference,
            )

        messages.success(request, "Withdrawal successful.")
        return redirect("wallet")

    return render(
        request,
        "store/wallet_withdraw.html",
        {"bank_account": bank_account},
    )


# =========================================
# GET DATA PLANS FROM RESELLER
# =========================================
@login_required
def get_data_plans(request):

    try:
        response = requests.get(
            f"{RESELLER_BASE_URL}/data/plans/",
            headers=RESELLER_HEADERS,
            timeout=30,
        )

        print("STATUS CODE:", response.status_code)
        print("RAW RESPONSE:", response.text)

        try:
            data = response.json()
        except Exception:
            return JsonResponse({
                "status": False,
                "message": "API did not return JSON",
                "raw": response.text
            })

        return JsonResponse(data, safe=False)

    except Exception as e:
        return JsonResponse({
            "status": False,
            "message": str(e)
        })
@login_required
@require_POST
@csrf_protect
def initiate_service_payment(request, plan_id, category_slug=None):
    """
    Handles Airtime and Data purchases.

    Supported payment methods:
    - Wallet
    - Card via Paystack
    """

    try:
        data = json.loads(request.body)

        phone = data.get("phone", "").strip()
        payment_method = data.get("payment_method", "").strip().lower()

        if not phone:
            return JsonResponse({
                "status": False,
                "message": "Phone number is required."
            })

        if not re.match(r"^0\d{10}$", phone):
            return JsonResponse({
                "status": False,
                "message": "Enter a valid 11-digit Nigerian phone number."
            })

        if payment_method not in ("wallet", "card"):
            return JsonResponse({
                "status": False,
                "message": "Invalid payment method."
            })

        plan = get_object_or_404(
            ServicePlan.objects.select_related(
                "provider",
                "provider__category",
                "provider__vendor",
            ),
            id=plan_id,
            is_active=True,
        )

        service_type = get_service_type_from_plan(plan)

        if service_type not in ("airtime", "data"):
            return JsonResponse({
                "status": False,
                "message": "This payment route supports airtime and data only."
            })

        if plan.selling_price is None:
            return JsonResponse({
                "status": False,
                "message": "This service currently has no configured price."
            })

        amount = Decimal(plan.selling_price)
        if "expected_price" in data:
            try:
                price_matches = Decimal(str(data["expected_price"])) == amount
            except (InvalidOperation, ValueError):
                price_matches = False
            if not price_matches:
                return JsonResponse({"status": False, "message": "The price changed. Reload this page to review the new total."})


        if amount <= Decimal("0.00"):
            return JsonResponse({
                "status": False,
                "message": "Invalid service price."
            })

        user = request.user

        # ---------------------------------------------------------
        # VALIDATE PROVIDER CONFIG
        # ---------------------------------------------------------
        if service_type == "airtime":
            if not plan.vendor_provider_id:
                return JsonResponse({
                    "status": False,
                    "message": "This airtime provider is not configured correctly."
                })

            provider_id = plan.vendor_provider_id
            bundle_id = None

        else:
            if not plan.vendor_bundle_id:
                return JsonResponse({
                    "status": False,
                    "message": "This data bundle is not configured correctly."
                })

            if settings.DATA_QUOTE_GUARD_ENABLED and not data_quote_allows_checkout(plan, payment_method):
                return JsonResponse({
                    "status": False,
                    "message": "This data bundle is temporarily unavailable.",
                })
            provider_id = None
            bundle_id = plan.vendor_bundle_id

        # =========================================================
        # WALLET PAYMENT
        # =========================================================
        if payment_method == "wallet":

            if user.wallet_balance < amount:
                return JsonResponse({
                    "status": False,
                    "message": (
                        f"Insufficient wallet balance. "
                        f"Required: ₦{amount:,.2f}"
                    )
                })

            reference = (
                f"{service_type.upper()}-"
                f"{uuid.uuid4().hex[:12].upper()}"
            )

            with transaction.atomic():

                service_txn = AirtimeTransaction.objects.create(
                    user=user,
                    service_plan=plan,
                    phone=phone,
                    amount_paid=amount,
                    payment_method="wallet",
                    reference=reference,
                    status="pending",
                    provider_id=provider_id,
                    bundle_id=bundle_id,
                )

                user.debit_wallet(
                    amount=amount,
                    source=f"{service_type}_purchase",
                    reference=reference,
                    description=(
                        f"{service_type.capitalize()} purchase "
                        f"for {phone}"
                    ),
                )

            # -----------------------------------------------------
            # CALL SERVICE PROVIDER
            # -----------------------------------------------------
            try:
                if service_type == "airtime":

                    api_response = purchase_airtime(
                        provider=plan.provider,
                        provider_id=plan.vendor_provider_id,
                        phone=phone,
                        amount=airtime_face_value(plan, amount),
                        reference=service_txn.reference,
                    )

                    if hasattr(api_response, "json"):
                        api_response = api_response.json()

                else:
                    api_url = (
                        f"{RESELLER_BASE_URL.rstrip('/')}"
                        "/api/v1/resellers/data/purchase/"
                    )

                    response = requests.post(
                        api_url,
                        headers=RESELLER_HEADERS,
                        json={
                            "bundle_id": int(plan.vendor_bundle_id),
                            "phone_number": phone,
                        },
                        timeout=30,
                    )

                    content_type = response.headers.get(
                        "Content-Type",
                        ""
                    ).lower()

                    if "application/json" in content_type:
                        try:
                            api_response = response.json()
                        except ValueError:
                            api_response = {
                                "status": "false",
                                "message": (
                                    "Data service is temporarily unavailable."
                                ),
                            }
                    else:
                        if settings.DEBUG:
                            print(
                                "Data provider returned non-JSON response:",
                                response.status_code,
                                response.text[:300],
                            )

                        api_response = {
                            "status": "false",
                            "message": (
                                "Data service is temporarily unavailable."
                            ),
                        }

            except requests.Timeout:
                api_response = {
                    "status": "false",
                    "message": (
                        f"{service_type.capitalize()} provider timed out."
                    ),
                }

            except requests.RequestException as exc:
                if settings.DEBUG:
                    print(
                        f"{service_type} provider network error:",
                        exc,
                    )

                api_response = {
                    "status": "false",
                    "message": (
                        f"{service_type.capitalize()} service "
                        "is temporarily unavailable."
                    ),
                }

            except Exception as exc:
                if settings.DEBUG:
                    print(
                        f"{service_type} provider error:",
                        exc,
                    )

                api_response = {
                    "status": "false",
                    "message": (
                        f"{service_type.capitalize()} service "
                        "is temporarily unavailable."
                    ),
                }

            if isinstance(api_response, dict) and api_response.get("status") == "pending":
                return JsonResponse({
                    "status": True, "message": "Your airtime purchase is being confirmed. Please check wallet history before trying again.",
                    "reference": reference, "redirect_url": reverse("wallet"),
                })

            provider_success = (
                isinstance(api_response, dict)
                and str(
                    api_response.get("status", "")
                ).lower()
                in ("true", "success")
            )

            # -----------------------------------------------------
            # WALLET SUCCESS
            # -----------------------------------------------------
            if provider_success:

                service_txn.status = "success"
                service_txn.save(
                    update_fields=["status"]
                )

                reward = plan.reward_amount

                if reward > Decimal("0.00"):
                    user.credit_wallet(
                        amount=reward,
                        source="cashback_reward",
                        reference=f"REWARD-{reference}",
                        description=(
                            f"Cashback reward for "
                            f"{service_type} purchase"
                        ),
                    )

                return JsonResponse({
                    "status": True,
                    "message": (
                        f"{service_type.capitalize()} "
                        "purchase successful."
                    ),
                    "reference": reference,
                    "redirect_url": (
                        reverse("payment_success")
                        + f"?reference={reference}"
                    ),
                })

            # -----------------------------------------------------
            # WALLET FAILURE + REFUND
            # -----------------------------------------------------
            refund_reference = f"REFUND-{reference}"

            with transaction.atomic():

                service_txn.status = "failed"
                service_txn.save(
                    update_fields=["status"]
                )

                if not WalletTransaction.objects.filter(
                    reference=refund_reference
                ).exists():

                    user.credit_wallet(
                        amount=amount,
                        source=f"{service_type}_refund",
                        reference=refund_reference,
                        description=(
                            f"Automatic refund for failed "
                            f"{service_type} purchase"
                        ),
                    )

            provider_message = None

            if isinstance(api_response, dict):
                provider_message = api_response.get("message")

            if service_type == "data":
                user_message = (
                    "Data service is temporarily unavailable. "
                    "Your wallet has been refunded automatically."
                )

            elif provider_message:
                user_message = (
                    f"{provider_message}. "
                    "Your wallet has been refunded automatically."
                )

            else:
                user_message = (
                    f"{service_type.capitalize()} service "
                    "is temporarily unavailable. "
                    "Your wallet has been refunded automatically."
                )

            return JsonResponse({
                "status": False,
                "message": user_message,
            })

        # =========================================================
        # CARD PAYMENT VIA PAYSTACK
        # =========================================================
        reference = (
            f"CARD-{service_type.upper()}-"
            f"{uuid.uuid4().hex[:12].upper()}"
        )

        card_txn = AirtimeTransaction.objects.create(
            user=user,
            service_plan=plan,
            phone=phone,
            amount_paid=amount,
            payment_method="card",
            reference=reference,
            status="pending",
            provider_id=provider_id,
            bundle_id=bundle_id,
        )

        request.session[f"pending_service_{reference}"] = {
            "transaction_id": card_txn.id,
            "service_type": service_type,
        }

        request.session.modified = True

        callback_url = request.build_absolute_uri(
            reverse("verify_service_payment")
        )

        result = initialize_paystack(
            email=user.email,
            amount=int(amount * 100),
            reference=reference,
            callback_url=callback_url,
        )

        if not result.get("status"):

            card_txn.status = "failed"
            card_txn.save(
                update_fields=["status"]
            )

            request.session.pop(
                f"pending_service_{reference}",
                None,
            )

            return JsonResponse({
                "status": False,
                "message": result.get(
                    "message",
                    "Card payment could not be initialized."
                ),
            })

        authorization_url = (
            result.get("data", {})
            .get("authorization_url")
        )

        if not authorization_url:

            card_txn.status = "failed"
            card_txn.save(
                update_fields=["status"]
            )

            request.session.pop(
                f"pending_service_{reference}",
                None,
            )

            return JsonResponse({
                "status": False,
                "message": (
                    "Paystack did not return a payment page."
                ),
            })

        return JsonResponse({
            "status": True,
            "authorization_url": authorization_url,
            "reference": reference,
        })

    except json.JSONDecodeError:
        return JsonResponse({
            "status": False,
            "message": "Invalid request data."
        })

    except ValidationError as exc:
        return JsonResponse({
            "status": False,
            "message": str(exc)
        })

    except Exception as exc:

        if settings.DEBUG:
            print(
                "initiate_service_payment error:",
                exc,
            )

        return JsonResponse({
            "status": False,
            "message": "Service temporarily unavailable."
        })

def card_service_orders():
    return AirtimeTransaction.objects.filter(payment_method="card").select_related(
        "user", "service_plan__provider__category", "service_plan__provider__vendor",
    )


def complete_card_service_order(order, payment):
    if (
        not isinstance(payment, dict)
        or payment.get("status") != "success"
        or payment.get("reference") != order.reference
        or payment.get("currency") != "NGN"
        or type(payment.get("amount")) is not int
        or payment["amount"] != int(order.amount_paid * 100)
    ):
        return False

    if not AirtimeTransaction.objects.filter(pk=order.pk, status="pending").update(status="processing"):
        return True

    plan = order.service_plan
    service_type = get_service_type_from_plan(plan)
    if service_type not in ("airtime", "data") or not order.user_id:
        return True

    try:
        if settings.PAYSTACK_SECRET_KEY.startswith("sk_test_"):
            delivery = {"status": "success"}
        elif service_type == "airtime":
            delivery = purchase_airtime(
                provider=plan.provider, provider_id=order.provider_id or plan.vendor_provider_id,
                phone=order.phone, amount=airtime_face_value(plan, order.amount_paid),
                reference=order.reference,
            )
        else:
            response = requests.post(
                f"{RESELLER_BASE_URL.rstrip('/')}/api/v1/resellers/data/purchase/",
                headers=RESELLER_HEADERS,
                json={"bundle_id": order.bundle_id or plan.vendor_bundle_id, "phone_number": order.phone},
                timeout=30,
            )
            response.raise_for_status()
            delivery = response.json()
    except (requests.RequestException, ValueError, AttributeError):
        # Delivery may have happened before the provider timed out. Leave it for reconciliation.
        return True

    status = str(delivery.get("status", "")).lower() if isinstance(delivery, dict) else ""
    if status in ("true", "success"):
        with transaction.atomic():
            AirtimeTransaction.objects.filter(pk=order.pk).update(status="success")
            reward = plan.reward_amount
            if reward and not settings.PAYSTACK_SECRET_KEY.startswith("sk_test_"):
                order.user.credit_wallet(
                    reward, source="cashback_reward", reference=f"REWARD-{order.reference}",
                    description=f"Cashback reward for {service_type} purchase",
                )
    elif status in ("false", "failed"):
        try:
            response = requests.post(
                "https://api.paystack.co/refund",
                headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
                json={"transaction": order.reference, "amount": int(order.amount_paid * 100)},
                timeout=30,
            )
            response.raise_for_status()
            if response.json().get("status") is True:
                AirtimeTransaction.objects.filter(pk=order.pk).update(status="refund_pending")
        except (requests.RequestException, ValueError, AttributeError):
            pass
    return True


@login_required
def verify_service_payment(request):
    reference = request.GET.get("reference") or request.GET.get("trxref")
    order = card_service_orders().filter(user=request.user, reference=reference).first()
    if order is None:
        messages.error(request, "Transaction could not be found.")
        return redirect("wallet")

    if order.status == "pending":
        try:
            result = verify_paystack(order.reference)
            if result.get("status") is True:
                complete_card_service_order(order, result.get("data"))
        except (requests.RequestException, ValueError, AttributeError):
            pass
    request.session.pop(f"pending_service_{order.reference}", None)
    return redirect(reverse("payment_success") + f"?reference={order.reference}")


def payment_success(request):
    reference = request.GET.get("reference", "")
    txn = None
    if request.user.is_authenticated:
        if reference.startswith("WALLET-"):
            txn = WalletTransaction.objects.filter(user=request.user, reference=reference, status="success").first()
        else:
            txn = AirtimeTransaction.objects.filter(user=request.user, reference=reference).first()

    return render(request, "store/payment_successful.html", {
        "reference": reference, "txn": txn,
        "test_purchase": bool(txn and getattr(txn, "payment_method", None) == "card" and settings.PAYSTACK_SECRET_KEY.startswith("sk_test_")),
    })


# ==============================
# AUTH & OTP
# ==============================
SIGNUP_PASSWORD_SYMBOL_PATTERN = r"[!@#$%^&*()_+=\-{}[\]:;\"'<>,.?/]"


def password_is_strong(password: str) -> bool:
    return (
        len(password) >= 8
        and re.search(r"[A-Z]", password)
        and re.search(r"[a-z]", password)
        and re.search(r"[0-9]", password)
        and re.search(SIGNUP_PASSWORD_SYMBOL_PATTERN, password)
    )


def send_otp(email: str, otp: str):
    send_mail(
        subject="Payvict Verification Code",
        message=f"Your verification code is {otp}\n\nValid for 10 minutes.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )


@csrf_protect
def register(request):
    if request.user.is_authenticated:
        return redirect("wallet")

    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password")
        password2 = request.POST.get("password2")
        phone = normalize_phone(request.POST.get("phone", ""))

        if not phone:
            messages.error(request, "Enter a valid Nigerian phone number.")
            return redirect("register")
        if User.objects.filter(phone=phone).exists():
            messages.error(request, "Phone number already registered. Please sign in.")
            return redirect("register")

        if not email or "@" not in email or not password:
            messages.error(request, "Valid email and password required.")
            return redirect("register")

        if password != password2:
            messages.error(request, "Passwords do not match.")
            return redirect("register")

        if not password_is_strong(password):
            messages.error(request, "Password must be 8+ chars with uppercase, lowercase, number, and symbol.")
            return redirect("register")

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already registered.")
            return redirect("register")

        otp = str(random.randint(100000, 999999))

        try:
            send_otp(email, otp)
        except OSError:
            messages.error(request, "We couldn't send your verification email. Please try again later.")
            return redirect("register")

        request.session["pending_user"] = {
            "email": email,
            "phone": phone,
            "first_name": request.POST.get("first_name", "").strip(),
            "last_name": request.POST.get("last_name", "").strip(),
            "password": password,
            "otp": otp,
            "expires_at": int(time.time()) + 600,
            "attempts": 0,
            "resend_count": 0,
        }
        request.session.modified = True

        messages.success(request, "Verification code sent!")
        return redirect("verify_otp")

    return render(request, "store/register.html", {"password_symbol_pattern": SIGNUP_PASSWORD_SYMBOL_PATTERN, "google_enabled": google_enabled()})


@csrf_protect
def verify_otp(request):
    data = request.session.get("pending_user")
    if not data or time.time() > data["expires_at"]:
        request.session.pop("pending_user", None)
        messages.error(request, "Session expired. Please register again.")
        return redirect("register")

    if request.method == "POST":
        otp_input = request.POST.get("otp", "").strip()

        if otp_input != data["otp"]:
            data["attempts"] += 1
            request.session["pending_user"] = data
            request.session.modified = True

            if data["attempts"] >= 5:
                request.session.pop("pending_user", None)
                messages.error(request, "Too many failed attempts.")
                return redirect("register")

            messages.error(request, "Invalid code.")
            return redirect("verify_otp")

        # Success
        email = data["email"]
        password = data["password"]
        request.session.pop("pending_user", None)

        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, "Email already registered. Please sign in.")
            return redirect("login")
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=email, email=email, password=password,
                    phone=data.get("phone"),
                    first_name=data.get("first_name", ""),
                    last_name=data.get("last_name", ""),
                )
        except IntegrityError:
            messages.error(request, "Email or phone number already registered. Please sign in.")
            return redirect("login")

        login(request, user)
        return redirect("home")

    return render(request, "store/verify_otp.html")


@csrf_protect
def resend_otp(request):
    data = request.session.get("pending_user")
    if not data:
        messages.error(request, "No active session.")
        return redirect("register")

    if data["resend_count"] >= 5:
        request.session.pop("pending_user", None)
        messages.error(request, "Max resends reached.")
        return redirect("register")

    new_otp = str(random.randint(100000, 999999))
    try:
        send_otp(data["email"], new_otp)
    except OSError:
        messages.error(request, "We couldn't send your verification email. Please try again later.")
        return redirect("verify_otp")

    data.update({
        "otp": new_otp,
        "expires_at": int(time.time()) + 600,
        "resend_count": data["resend_count"] + 1,
        "attempts": 0,
    })
    request.session["pending_user"] = data
    request.session.modified = True

    messages.success(request, "New code sent!")
    return redirect("verify_otp")


@csrf_protect
def custom_login(request):
    next_url = request.POST.get("next") or request.GET.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = ""
    if request.method == "POST":
        email = request.POST.get("username", "").strip().lower()
        password = request.POST.get("password")

        if not email or not password:
            messages.error(request, "Email or phone number and password required.")
            return redirect(request.get_full_path())

        user = authenticate(request, username=email, password=password)
        if user:
            login(request, user)
            return redirect(next_url or "home")

        messages.error(request, "Invalid credentials.")
        return redirect(request.get_full_path())

    return render(request, "store/login.html", {"google_enabled": google_enabled(), "next_url": next_url})


def custom_logout(request):
    logout(request)
    return redirect("login")

## ==================================
# SERVICE DASHBOARD - Airtime/Data
# ===================================

def listed_service_plans(slug):
    plans = ServicePlan.objects.filter(
        provider__category__slug=slug, provider__category__is_active=True, provider__is_active=True, is_active=True,
    ).select_related("provider")
    if slug in ("airtime", "data", "internet-data"):
        vendor_id_field = "vendor_provider_id" if slug == "airtime" else "vendor_bundle_id"
        plans = plans.filter(selling_price__gt=0, **{f"{vendor_id_field}__gt": 0})
        if slug == "airtime":
            plans = plans.exclude(provider__vendor__api_url="").filter(
                provider__vendor__isnull=False,
            )

    return plans


@login_required
def service_checkout(request, slug, plan_id):
    if slug not in ("airtime", "data", "internet-data"):
        raise Http404
    plan = get_object_or_404(listed_service_plans(slug), pk=plan_id)
    return render(request, "store/service_checkout.html", {"plan": plan, "slug": slug})


def service_dashboard(request, slug):
    category = get_object_or_404(ServiceCategory.objects.exclude(slug="insurance"), slug=slug, is_active=True)
    plans = listed_service_plans(slug)
    if slug in ("data", "internet-data"):
        for plan in plans:
            title, separator, suffix = plan.name.rpartition(" (")
            if separator and re.fullmatch(r"\d+\s+days?\)", suffix, re.IGNORECASE):
                plan.display_title = title
                plan.display_validity = suffix[:-1].lower()
    providers = ServiceProvider.objects.filter(
        category=category, is_active=True,
    ).order_by("order")

    provider_id = request.GET.get("provider")
    selected_provider = providers.filter(pk=provider_id).first() if provider_id and provider_id.isdecimal() else None

    # Empty querysets (no cable/electricity here)
    cable_transactions = CableTransaction.objects.none()
    electricity_transactions = ElectricityTransaction.objects.none()

    context = {
        "category": category,
        "providers": providers,
        "plans": plans,
        "selected_provider": selected_provider,
        "cable_transactions": cable_transactions,
        "electricity_transactions": electricity_transactions,
    }
    return render(request, "store/service_dashboard.html", context)


## ================================================================
# Tv Subscription
# ================================================================
def process_service_payment(user, plan, phone=None, cardnumber=None, meter_number=None, 
                           meter_type="prepaid", payment_method="wallet", service_type="airtime"):
    """
    service_type: "airtime", "data", "cable", "electricity"
    """
    reference = f"{service_type.upper()}-{uuid.uuid4().hex[:12].upper()}"
    amount = float(plan.selling_price)
    
    if payment_method == "wallet":
        if user.wallet_balance < amount:
            return {"status": False, "message": f"Insufficient balance. Need ₦{amount:,.2f}"}

        with transaction.atomic():
            # Debit wallet
            user.debit_wallet(
                amount=amount,
                source=f"{service_type}_purchase",
                reference=reference
            )

            # Determine correct transaction model
            txn_model_map = {
                "airtime": AirtimeTransaction,
                "data": AirtimeTransaction,      # same model for both airtime & data
                "cable": CableTransaction,
                "electricity": ElectricityTransaction
            }
            txn_model = txn_model_map.get(service_type)

            if not txn_model:
                raise ValueError(f"Unsupported service_type: {service_type}")

            # Create transaction record
            txn_data = {
                "user": user,
                "service_plan": plan,
                "phone": phone,
                "amount_paid": amount,
                "reference": reference,
                "status": "pending",  # will be updated after API call
                "payment_method": payment_method,
            }

            if service_type in ["airtime", "data"]:
                # For data → prefer bundle_id if set, else fallback to vendor_plan_id
                # For airtime → prefer provider_id if set
                if service_type == "data":
                    txn_data["bundle_id"] = plan.vendor_plan_id  # or manual override if needed
                else:
                    txn_data["provider_id"] = plan.vendor_plan_id

            elif service_type == "cable":
                txn_data["cardnumber"] = cardnumber

            elif service_type == "electricity":
                txn_data["meter_number"] = meter_number
                txn_data["meter_type"] = meter_type

            txn = txn_model.objects.create(**txn_data)

            # Optional cashback reward
            reward = getattr(plan, "reward_amount", Decimal("0.00"))
            if reward > 0:
                user.credit_wallet(
                    amount=reward,
                    source="cashback_reward",
                    reference=f"REWARD-{reference}"
                )

        return {"status": True, "reference": reference, "transaction": txn}

    # Card payment would go here (Paystack flow)
    return {"status": False, "message": "Only wallet payment supported at the moment"}

## ==============================
# Purchase Functions (API calls)
# ===============================

def purchase_data(network, plan_id, phone):
    print("=== HIT CHEAPDATA DATA ENDPOINT ===")
    print("Network:", network)
    print("Plan ID:", plan_id)
    print("Phone:", phone)

    payload = {
        "network": network,
        "plan_id": str(plan_id),
        "phone": phone
    }

    print("FINAL PAYLOAD >>>", payload)

    try:
        response = requests.post(
            f"{RESELLER_BASE_URL}/data/purchase/",
            json=payload,
            headers=RESELLER_HEADERS,
            timeout=30,
        )

        print("HTTP Status:", response.status_code)
        print("Raw Response:", response.text)

        try:
            return response.json()
        except Exception:
            return {
                "status": "false",
                "message": "Invalid JSON response",
                "raw": response.text
            }

    except requests.RequestException as e:
        print("Request Error:", e)
        return {
            "status": "false",
            "message": "Network error"
        }

def airtime_face_value(plan, charged_amount):
    if plan.code == "MTN-100":
        return 100
    return charged_amount


def purchase_airtime(provider, provider_id, phone, amount, reference=None):
    if settings.VTPASS_AIRTIME_ENABLED:
        from .bills import vtpass_post
        from datetime import datetime
        from zoneinfo import ZoneInfo
        services = {"mtn": "mtn", "airtel": "airtel", "glo": "glo", "9mobile": "etisalat", "t2": "etisalat"}
        service = services.get(provider.name.strip().casefold())
        if not service:
            return {"status": "failed", "message": "This airtime network is currently unavailable."}
        suffix = hashlib.sha256((reference or uuid.uuid4().hex).encode()).hexdigest()[:20]
        request_id = datetime.now(ZoneInfo("Africa/Lagos")).strftime("%Y%m%d%H%M") + suffix
        if reference:
            order = AirtimeTransaction.objects.filter(reference=reference).first()
            if order:
                request_id = order.supplier_reference or request_id
                AirtimeTransaction.objects.filter(pk=order.pk).update(supplier_reference=request_id)
        result = vtpass_post("pay", {
            "request_id": request_id, "serviceID": service, "amount": float(amount), "phone": phone,
        })
        content = result.get("content")
        txn = content.get("transactions", {}) if isinstance(content, dict) else {}
        if result.get("code") == "000" and txn.get("status") == "delivered":
            return {"status": "success"}
        if result.get("code") in ("010", "011", "012", "013", "016", "017", "091") or txn.get("status") in ("failed", "reversed"):
            return {"status": "failed", "message": "The airtime purchase was unsuccessful."}
        return {"status": "pending"}
    print("=== HIT CHEAPDATA AIRTIME ENDPOINT ===")
    print("Provider:", provider.name)
    print("API URL:", provider.vendor.api_url)
    print("Provider ID:", provider_id)
    print("Phone:", phone)
    print("Amount:", amount)

    payload = {
        "provider_id": provider_id,
        "phone_number": phone,
        "amount": int(amount),
    }
    print("Sending payload:", payload)

    response = requests.post(
        f"{provider.vendor.api_url}/airtime/purchase/",
        json=payload,
        headers={
            "Authorization": f"Bearer {settings.CHEAPDATAHUB_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=30,
    
    )

    print("HTTP Status:", response.status_code)
    print("CheapData response:", response.text)
    return response.json()

    # airtime_buy remains fine — it's already secure with get_object_or_404 + is_active
def airtime_buy(request, plan_id):
    plan = get_object_or_404(ServicePlan, id=plan_id, is_active=True)
    return render(
        request,
        "store/airtime_buy.html",
        {
            "plan": plan,
            "provider": plan.provider,
            "category": plan.provider.category,
        },
    )


def blog_list(request):
    posts = BlogPost.objects.filter(published=True).order_by("-created_at")
    return render(request, "blog/blog_list.html", {"posts": posts})


def blog_detail(request, slug):
    post = get_object_or_404(BlogPost, slug=slug, published=True)
    return render(request, "blog/blog_detail.html", {"post": post})


def review_thank_you(request):
    return render(request, "store/review_thank_you.html")


@require_POST
def submit_review(request):
    name = request.POST.get("name", "").strip()
    email = request.POST.get("email", "").strip()
    rating = request.POST.get("rating")
    comment = request.POST.get("comment", "").strip()
    location = request.POST.get("location", "").strip()

    if not rating or not comment:
        messages.error(request, "Rating and comment are required.")
        return redirect("home")

    if not request.user.is_authenticated and (not name or not email):
        messages.error(request, "Name and email are required for guest reviews.")
        return redirect("home")

    Review.objects.create(
        name=name or (request.user.get_full_name() if request.user.is_authenticated else "Anonymous"),
        email=email or (request.user.email if request.user.is_authenticated else ""),
        location=location,
        rating=int(rating),
        comment=comment,
    )

    messages.success(request, "Thank you for your review!")
    return redirect("review_thank_you")


