import json
import uuid
import hmac
import hashlib
import requests
from decimal import Decimal
import re
import time
import random

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError

User = get_user_model()

from .models import (
    Product,
    HeroBanner,
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

from .paystack import initialize_paystack

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
    hero = HeroBanner.objects.filter(page="home", is_active=True).first()
    products = Product.objects.filter(is_active=True)
    faq_list = FAQ.objects.filter(is_active=True)
    services = ServiceCategory.objects.filter(is_active=True).order_by("order")

    wallet_balance = (
        request.user.wallet_balance if request.user.is_authenticated else Decimal("0.00")
    )

    return render(
        request,
        "store/home.html",
        {
            "hero": hero,
            "products": products,
            "services": services,
            "faq_list": faq_list,
            "quantity_options": range(1, 11),
            "wallet_balance": wallet_balance,
        },
    )

def faq_view(request):
    faq_list = FAQ.objects.all().order_by('id')  # ← safe option
    # Or if you have a date field:
    # faq_list = FAQ.objects.all().order_by('-created_at')
    return render(request, 'store/faq.html', {'faq_list': faq_list})

    
@csrf_exempt
def paystack_webhook(request):
    signature = request.headers.get("x-paystack-signature")
    if not signature:
        return HttpResponse("No signature", status=400)

    computed = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(),
        request.body,
        hashlib.sha512
    ).hexdigest()

    if not hmac.compare_digest(computed, signature):
        return HttpResponse("Invalid signature", status=400)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    if payload.get("event") != "charge.success":
        return HttpResponse("Ignored event", status=200)

    ref = payload.get("data", {}).get("reference")
    if not ref or not ref.startswith("WALLET-"):
        return HttpResponse("Invalid reference", status=200)

    try:
        txn = WalletTransaction.objects.get(reference=ref)
    except WalletTransaction.DoesNotExist:
        return HttpResponse("Unknown reference", status=200)

    if txn.status == "success":
        return HttpResponse("Already processed", status=200)

    if txn.status == "pending":
        try:
            with transaction.atomic():
                locked_txn = WalletTransaction.objects.select_for_update().get(reference=ref)
                if locked_txn.status == "pending":
                    locked_txn.status = "success"
                    locked_txn.save(update_fields=["status"])
        except WalletTransaction.DoesNotExist:
            pass

    return HttpResponse("OK", status=200)


@login_required
def wallet(request):
    user = request.user
    transactions_qs = user.wallet_transactions.order_by("-created_at")
    paginator = Paginator(transactions_qs, 25)
    page_number = request.GET.get("page")
    wallet_transactions = paginator.get_page(page_number)

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
        amount = Decimal(data.get("amount", "0"))

        if amount < Decimal("100"):
            return JsonResponse({"status": False, "message": "Minimum funding amount is ₦100"})

        if amount > Decimal("5000000"):  # Reasonable cap
            return JsonResponse({"status": False, "message": "Amount too high"})

        reference = f"WALLET-{uuid.uuid4().hex[:12].upper()}"

        request.session["pending_wallet_fund"] = {
            "reference": reference,
            "amount": str(amount),
        }
        request.session.modified = True

        result = initialize_paystack(
            email=request.user.email,
            amount=int(amount * 100),
            reference=reference,
            callback_url=request.build_absolute_uri(reverse("verify_wallet_funding")),
        )

        if not result.get("status"):
            request.session.pop("pending_wallet_fund", None)
            return JsonResponse({"status": False, "message": result.get("message", "Payment failed")})

        return JsonResponse({
            "status": True,
            "data": {"authorization_url": result["data"]["authorization_url"]}
        })

    except Exception as e:
        print("Wallet fund init error:", e)
        return JsonResponse({"status": False, "message": "Service unavailable"})


@login_required
def verify_wallet_funding(request):
    reference = request.GET.get("reference")
    if not reference:
        messages.error(request, "Invalid reference")
        return redirect("wallet")

    pending = request.session.get("pending_wallet_fund")
    if not pending or pending.get("reference") != reference:
        messages.info(request, "Session expired or invalid")
        return redirect("wallet")

    if WalletTransaction.objects.filter(reference=reference, status="success").exists():
        messages.info(request, "Already credited")
        request.session.pop("pending_wallet_fund", None)
        return redirect("wallet")

    headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
    try:
        response = requests.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers=headers,
            timeout=30
        )
        result = response.json()
    except Exception as e:
        messages.error(request, "Verification failed")
        return redirect("wallet")

    if not result.get("status") or result["data"]["status"] != "success":
        messages.error(request, "Payment failed")
        return redirect("wallet")

    amount = Decimal(pending["amount"])

    with transaction.atomic():
        WalletTransaction.objects.create(
            user=request.user,
            amount=amount,
            transaction_type="credit",
            source="funding",
            status="success",
            reference=reference,
        )

    request.session.pop("pending_wallet_fund", None)
    messages.success(request, f"Wallet credited with ₦{amount:,}!")
    return redirect("wallet")


@login_required
def add_bank_account(request):
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
                        amount=amount,
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

@login_required
def verify_service_payment(request):
    """
    Paystack callback for Airtime and Data card payments.

    Flow:
    1. Verify payment with Paystack.
    2. Confirm amount matches.
    3. Deliver airtime/data through provider.
    4. Mark transaction successful or failed.
    5. Request Paystack refund if delivery fails.
    """

    reference = (
        request.GET.get("reference")
        or request.GET.get("trxref")
    )

    if not reference:
        messages.error(
            request,
            "Invalid payment reference."
        )
        return redirect("payment_success")

    txn = (
        AirtimeTransaction.objects
        .select_related(
            "service_plan",
            "service_plan__provider",
            "service_plan__provider__category",
            "service_plan__provider__vendor",
        )
        .filter(reference=reference)
        .first()
    )

    if not txn:
        messages.error(
            request,
            "Transaction could not be found."
        )
        return redirect("payment_success")

    if txn.user_id != request.user.id:
        messages.error(
            request,
            "This transaction does not belong to your account."
        )
        return redirect("payment_success")

    if txn.status == "success":
        messages.info(
            request,
            "This transaction has already been processed."
        )
        return redirect(
            reverse("payment_success")
            + f"?reference={reference}"
        )

    if txn.payment_method != "card":
        messages.error(
            request,
            "Invalid payment method for this callback."
        )
        return redirect("payment_success")

    plan = txn.service_plan

    service_type = get_service_type_from_plan(plan)

    if service_type not in ("airtime", "data"):

        txn.status = "failed"
        txn.save(
            update_fields=["status"]
        )

        messages.error(
            request,
            "Invalid service configuration."
        )

        return redirect("payment_success")

    # =========================================================
    # VERIFY PAYSTACK PAYMENT
    # =========================================================
    try:
        response = requests.get(
            (
                "https://api.paystack.co/"
                f"transaction/verify/{reference}"
            ),
            headers={
                "Authorization": (
                    f"Bearer "
                    f"{settings.PAYSTACK_SECRET_KEY}"
                )
            },
            timeout=30,
        )

        result = response.json()

    except requests.RequestException as exc:

        if settings.DEBUG:
            print(
                "Paystack verification network error:",
                exc,
            )

        messages.error(
            request,
            "Unable to verify your payment right now."
        )

        return redirect(
            reverse("payment_success")
            + f"?reference={reference}"
        )

    except ValueError:

        messages.error(
            request,
            "Paystack returned an invalid response."
        )

        return redirect(
            reverse("payment_success")
            + f"?reference={reference}"
        )

    paystack_data = result.get("data", {})

    if (
        not result.get("status")
        or paystack_data.get("status") != "success"
    ):

        txn.status = "failed"
        txn.save(
            update_fields=["status"]
        )

        messages.error(
            request,
            "Card payment was not successful."
        )

        return redirect(
            reverse("payment_success")
            + f"?reference={reference}"
        )

    # =========================================================
    # VERIFY PAID AMOUNT
    # =========================================================
    paid_amount = (
        Decimal(
            str(paystack_data.get("amount", 0))
        )
        / Decimal("100")
    )

    if abs(
        paid_amount - txn.amount_paid
    ) > Decimal("0.01"):

        txn.status = "failed"
        txn.save(
            update_fields=["status"]
        )

        messages.error(
            request,
            "Payment amount did not match the transaction."
        )

        return redirect(
            reverse("payment_success")
            + f"?reference={reference}"
        )

    # =========================================================
    # DELIVER SERVICE
    # =========================================================
    try:

        if service_type == "airtime":

            if not plan.vendor_provider_id:
                raise ValueError(
                    "Missing airtime provider ID."
                )

            api_response = purchase_airtime(
                provider=plan.provider,
                provider_id=plan.vendor_provider_id,
                phone=txn.phone,
                amount=txn.amount_paid,
            )

            if hasattr(api_response, "json"):
                api_response = api_response.json()

        else:

            if not plan.vendor_bundle_id:
                raise ValueError(
                    "Missing data bundle ID."
                )

            api_url = (
                f"{RESELLER_BASE_URL.rstrip('/')}"
                "/api/v1/resellers/data/purchase/"
            )

            provider_response = requests.post(
                api_url,
                headers=RESELLER_HEADERS,
                json={
                    "bundle_id": int(
                        plan.vendor_bundle_id
                    ),
                    "phone_number": txn.phone,
                },
                timeout=30,
            )

            content_type = (
                provider_response.headers.get(
                    "Content-Type",
                    ""
                )
                .lower()
            )

            if "application/json" in content_type:

                try:
                    api_response = (
                        provider_response.json()
                    )

                except ValueError:
                    api_response = {
                        "status": "false",
                        "message": (
                            "Data provider returned "
                            "an invalid response."
                        ),
                    }

            else:

                if settings.DEBUG:
                    print(
                        "Data provider returned non-JSON:",
                        provider_response.status_code,
                        provider_response.text[:300],
                    )

                api_response = {
                    "status": "false",
                    "message": (
                        "Data service is temporarily unavailable."
                    ),
                }

    except requests.RequestException as exc:

        if settings.DEBUG:
            print(
                f"{service_type} delivery network error:",
                exc,
            )

        api_response = {
            "status": "false",
            "message": (
                f"{service_type.capitalize()} "
                "provider is temporarily unavailable."
            ),
        }

    except Exception as exc:

        if settings.DEBUG:
            print(
                f"{service_type} delivery error:",
                exc,
            )

        api_response = {
            "status": "false",
            "message": (
                f"{service_type.capitalize()} "
                "delivery failed."
            ),
        }

    provider_success = (
        isinstance(api_response, dict)
        and str(
            api_response.get("status", "")
        ).lower()
        in (
            "true",
            "success",
        )
    )

    # =========================================================
    # DELIVERY SUCCESS
    # =========================================================
    if provider_success:

        txn.status = "success"
        txn.save(
            update_fields=["status"]
        )

        reward = plan.reward_amount

        if reward > Decimal("0.00"):

            reward_reference = (
                f"REWARD-{reference}"
            )

            if not WalletTransaction.objects.filter(
                reference=reward_reference
            ).exists():

                request.user.credit_wallet(
                    amount=reward,
                    source="cashback_reward",
                    reference=reward_reference,
                    description=(
                        f"Cashback reward for "
                        f"{service_type} purchase"
                    ),
                )

        request.session.pop(
            f"pending_service_{reference}",
            None,
        )

        messages.success(
            request,
            (
                f"{service_type.capitalize()} "
                "purchase successful."
            ),
        )

        return redirect(
            reverse("payment_success")
            + f"?reference={reference}"
        )

    # =========================================================
    # DELIVERY FAILED AFTER SUCCESSFUL CARD PAYMENT
    # =========================================================
    txn.status = "failed"
    txn.save(
        update_fields=["status"]
    )

    refund_started = False

    try:
        refund_response = requests.post(
            "https://api.paystack.co/refund",
            headers={
                "Authorization": (
                    f"Bearer "
                    f"{settings.PAYSTACK_SECRET_KEY}"
                ),
                "Content-Type": "application/json",
            },
            json={
                "transaction": reference,
                "amount": int(
                    txn.amount_paid * 100
                ),
            },
            timeout=30,
        )

        refund_result = refund_response.json()

        refund_started = bool(
            refund_result.get("status")
        )

        if settings.DEBUG:
            print(
                "Paystack refund response:",
                refund_result,
            )

    except Exception as exc:

        if settings.DEBUG:
            print(
                "Paystack refund error:",
                exc,
            )

    request.session.pop(
        f"pending_service_{reference}",
        None,
    )

    provider_message = None

    if isinstance(api_response, dict):
        provider_message = (
            api_response.get("message")
        )

    if refund_started:

        messages.error(
            request,
            (
                f"{service_type.capitalize()} delivery "
                "could not be completed. "
                "A card refund has been initiated."
            ),
        )

    else:

        messages.error(
            request,
            (
                provider_message
                or (
                    f"{service_type.capitalize()} "
                    "delivery failed. "
                    "Please contact support regarding "
                    "your card payment."
                )
            ),
        )

    return redirect(
        reverse("payment_success")
        + f"?reference={reference}"
    )

@login_required
@require_POST
@csrf_protect
def initiate_cable_payment(request, plan_id):
    try:
        data = json.loads(request.body)
        smartcard = data.get("smartcard", "").strip()
        phone = data.get("phone", "").strip()  # optional, for notification
        payment_method = data.get("payment_method")

        if not smartcard or payment_method not in ["wallet", "card"]:
            return JsonResponse({"status": False, "message": "Invalid data"})

        if len(smartcard) < 10:
            return JsonResponse({"status": False, "message": "Invalid Smartcard/IUC number"})

        plan = get_object_or_404(ServicePlan, id=plan_id, is_active=True)

        # Safety check
        if not plan.vendor_plan_id:
            return JsonResponse({"status": False, "message": "This plan is not configured for cable"})

        amount_naira = float(plan.selling_price)
        reference = f"CABLE-{uuid.uuid4().hex[:12].upper()}"
        user = request.user

        if payment_method == "wallet":
            if user.wallet_balance < amount_naira:
                return JsonResponse({"status": False, "message": "Insufficient balance"})
            
            with transaction.atomic():
                user.debit_wallet(amount=amount_naira, source="cable_purchase", reference=reference)
                
                cable_txn = CableTransaction.objects.create(
                    user=user,
                    service_plan=plan,
                    card_number=smartcard,
                    phone=phone,
                    amount_paid=amount_naira,
                    payment_method="wallet",
                    reference=reference,
                    status="pending"
                )

                # CALL CHEAPDATAHUB
                api_response = purchase_cable(plan.vendor_plan_id, smartcard, phone)

                if api_response.get("status") == "true":
                    cable_txn.status = "success"
                    cable_txn.save(update_fields=["status"])
                    
                    # Cashback
                    reward = plan.reward_amount or Decimal("0.00")
                    if reward > 0:
                        user.credit_wallet(reward, source="cashback_reward", reference=f"REWARD-{reference}")

                    return JsonResponse({
                        "status": True,
                        "message": "Subscription successful!",
                        "redirect_url": reverse("payment_success") + f"?reference={reference}"
                    })
                else:
                    # Refund on failure
                    user.credit_wallet(amount_naira, source="cable_refund", reference=f"REFUND-{reference}")
                    cable_txn.status = "failed"
                    cable_txn.save(update_fields=["status"])
                    return JsonResponse({
                        "status": False,
                        "message": api_response.get("message", "Subscription failed")
                    })

        # Card payment
        CableTransaction.objects.filter(user=user, status="pending").delete()
        
        with transaction.atomic():
            cable_txn = CableTransaction.objects.create(
                user=user,
                service_plan=plan,
                card_number=smartcard,
                phone=phone,
                amount_paid=amount_naira,
                payment_method="card",
                reference=reference,
                status="pending"
            )
            
            request.session[f"pending_cable_{reference}"] = {
                "plan_id": plan.id,
                "smartcard": smartcard,
                "phone": phone,
                "amount_naira": amount_naira,
            }
            request.session.modified = True

        result = initialize_paystack(
            email=user.email,
            amount=int(amount_naira * 100),
            reference=reference,
            callback_url=request.build_absolute_uri(reverse("verify_cable_payment")),
        )

        if result.get("status"):
            return JsonResponse({
                "status": True,
                "authorization_url": result["data"]["authorization_url"]
            })
        else:
            CableTransaction.objects.filter(reference=reference).delete()
            request.session.pop(f"pending_cable_{reference}", None)
            return JsonResponse({"status": False, "message": "Payment failed to initialize"})

    except Exception as e:
        print("Cable payment error:", e)
        return JsonResponse({"status": False, "message": "Service unavailable"})



@login_required
def verify_cable_payment(request):
    reference = request.GET.get("reference")
    if not reference:
        messages.error(request, "No reference provided")
        return redirect("payment_success")

    # Find pending cable transaction
    txn = CableTransaction.objects.filter(reference=reference, status="pending").first()
    if not txn:
        messages.info(request, "Transaction not found or already processed")
        return redirect("payment_success")

    # Verify payment with Paystack
    try:
        response = requests.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
            timeout=30
        )
        result = response.json()
    except Exception as e:
        print("Paystack verification error:", e)
        messages.error(request, "Failed to verify payment with bank")
        return redirect("payment_success")

    if not result.get("status") or result["data"]["status"] != "success":
        txn.status = "failed"
        txn.save(update_fields=["status"])
        messages.error(request, "Payment failed or was cancelled")
        return redirect("payment_success")

    paid_amount = Decimal(result["data"]["amount"]) / 100
    if abs(paid_amount - txn.amount_paid) > Decimal("0.01"):
        txn.status = "failed"
        txn.save(update_fields=["status"])
        messages.error(request, "Payment amount does not match")
        return redirect("payment_success")

    # PAYMENT SUCCESSFUL — NOW CALL CHEAPDATAHUB TO ACTIVATE SUBSCRIPTION
    try:
        api_response = purchase_cable(
            plan_id=txn.service_plan.vendor_plan_id,
            cardnumber=txn.card_number,
            phone=txn.phone or ""
        )

        if api_response.get("status") == "true":
            txn.status = "success"
            txn.save(update_fields=["status"])

            # Give cashback reward
            reward = txn.service_plan.reward_amount or Decimal("0.00")
            if reward > 0:
                request.user.credit_wallet(
                    amount=reward,
                    source="cashback_reward",
                    reference=f"REWARD-{reference}"
                )

            messages.success(request, "Cable subscription successful! Enjoy your channels!")
        else:
            txn.status = "failed"
            txn.save(update_fields=["status"])
            error_msg = api_response.get("message", "Unknown error from provider")
            messages.error(request, f"Subscription failed: {error_msg}")
    except Exception as e:
        print("CheapDataHub cable error:", e)
        txn.status = "failed"
        txn.save(update_fields=["status"])
        messages.error(request, "Network error while activating subscription")

    return redirect(reverse("payment_success") + f"?reference={reference}")


@login_required
@require_POST
@csrf_protect
def initiate_electricity_payment(request, plan_id):
    try:
        data = json.loads(request.body)
        meter_number = data.get("meter_number", "").strip()
        phone = data.get("phone", "").strip()
        meter_type = data.get("meter_type", "prepaid")
        amount_str = data.get("amount", "0").strip()  # ← NEW: user input amount
        payment_method = data.get("payment_method")

        # Validation
        if not meter_number or not amount_str or payment_method not in ["wallet", "card"]:
            return JsonResponse({"status": False, "message": "Missing required fields"})

        if len(meter_number) < 10:
            return JsonResponse({"status": False, "message": "Invalid meter number (min 10 digits)"})

        if meter_type not in ["prepaid", "postpaid"]:
            return JsonResponse({"status": False, "message": "Invalid meter type"})

        try:
            amount_naira = float(amount_str)
            if amount_naira < 100 or amount_naira > 100000:
                return JsonResponse({"status": False, "message": "Amount must be between ₦100 and ₦100,000"})
        except ValueError:
            return JsonResponse({"status": False, "message": "Invalid amount format"})

        # Get disco (provider/plan)
        plan = get_object_or_404(ServicePlan, id=plan_id, is_active=True)
        disco_id = plan.vendor_plan_id  # assuming this stores disco_id

        if not disco_id:
            return JsonResponse({"status": False, "message": "Provider not configured for electricity"})

        reference = f"ELEC-{uuid.uuid4().hex[:12].upper()}"
        user = request.user

        if payment_method == "wallet":
            if user.wallet_balance < amount_naira:
                return JsonResponse({"status": False, "message": f"Insufficient balance. Need ₦{amount_naira:,.2f}"})

            with transaction.atomic():
                user.debit_wallet(amount=amount_naira, source="electricity_purchase", reference=reference)

                elec_txn = ElectricityTransaction.objects.create(
                    user=user,
                    service_plan=plan,  # optional
                    meter_number=meter_number,
                    disco_id=disco_id,
                    meter_type=meter_type,
                    phone=phone,
                    amount_paid=amount_naira,
                    payment_method="wallet",
                    reference=reference,
                    status="pending"
                )

                # Call CheapDataHub
                api_response = purchase_electricity(
                    disco_id=disco_id,
                    meter_number=meter_number,
                    amount=amount_naira,
                    phone=phone,
                    meter_type=meter_type
                )

                if api_response.get("status") == "true":
                    elec_txn.status = "success"
                    elec_txn.token = api_response.get("token")
                    elec_txn.save(update_fields=["status", "token"])

                    # Cashback (if plan has reward, optional)
                    reward = plan.reward_amount or Decimal("0.00")
                    if reward > 0:
                        user.credit_wallet(reward, source="cashback_reward", reference=f"REWARD-{reference}")

                    return JsonResponse({
                        "status": True,
                        "message": f"Electricity payment successful! Token: {api_response.get('token', 'Processing...')}",
                        "redirect_url": reverse("payment_success") + f"?reference={reference}"
                    })
                else:
                    user.credit_wallet(amount_naira, source="electricity_refund", reference=f"REFUND-{reference}")
                    elec_txn.status = "failed"
                    elec_txn.save(update_fields=["status"])
                    return JsonResponse({
                        "status": False,
                        "message": api_response.get("message", "Payment failed")
                    })

        # Card payment (Paystack)
        ElectricityTransaction.objects.filter(user=user, status="pending").delete()

        with transaction.atomic():
            elec_txn = ElectricityTransaction.objects.create(
                user=user,
                service_plan=plan,
                meter_number=meter_number,
                disco_id=disco_id,
                meter_type=meter_type,
                phone=phone,
                amount_paid=amount_naira,
                payment_method="card",
                reference=reference,
                status="pending"
            )

            request.session[f"pending_elec_{reference}"] = {
                "plan_id": plan.id,
                "meter_number": meter_number,
                "meter_type": meter_type,
                "phone": phone,
                "amount_naira": amount_naira,
            }
            request.session.modified = True

        result = initialize_paystack(
            email=user.email,
            amount=int(amount_naira * 100),
            reference=reference,
            callback_url=request.build_absolute_uri(reverse("verify_electricity_payment")),
        )

        if result.get("status"):
            return JsonResponse({
                "status": True,
                "authorization_url": result["data"]["authorization_url"]
            })
        else:
            ElectricityTransaction.objects.filter(reference=reference).delete()
            request.session.pop(f"pending_elec_{reference}", None)
            return JsonResponse({"status": False, "message": "Payment failed to initialize"})

    except Exception as e:
        print("Electricity payment error:", e)
        return JsonResponse({"status": False, "message": "Service unavailable"})


@login_required
def verify_electricity_payment(request):
    reference = request.GET.get("reference")
    if not reference:
        messages.error(request, "No reference provided")
        return redirect("payment_success")

    # Find pending electricity transaction
    txn = ElectricityTransaction.objects.filter(reference=reference, status="pending").first()
    if not txn:
        messages.info(request, "Transaction not found or already processed")
        return redirect("payment_success")

    # Verify payment with Paystack
    try:
        response = requests.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
            timeout=30
        )
        result = response.json()
    except Exception as e:
        print("Paystack verification error:", e)
        messages.error(request, "Failed to verify payment with bank")
        return redirect("payment_success")

    if not result.get("status") or result["data"]["status"] != "success":
        txn.status = "failed"
        txn.save(update_fields=["status"])
        messages.error(request, "Payment failed or was cancelled")
        return redirect("payment_success")

    paid_amount = Decimal(result["data"]["amount"]) / 100
    if abs(paid_amount - txn.amount_paid) > Decimal("0.01"):
        txn.status = "failed"
        txn.save(update_fields=["status"])
        messages.error(request, "Payment amount does not match")
        return redirect("payment_success")

    # PAYMENT SUCCESSFUL — NOW CALL CHEAPDATAHUB TO PURCHASE ELECTRICITY
    try:
        api_response = purchase_electricity(
            disco_id=txn.disco_id,
            meter_number=txn.meter_number,
            amount=txn.amount_paid,
            phone=txn.phone or "",
            meter_type=txn.meter_type
        )

        if api_response.get("status") == "true":
            txn.status = "success"
            txn.token = api_response.get("token")  # save token for prepaid
            txn.save(update_fields=["status", "token"])

            # Give cashback reward
            reward = txn.service_plan.reward_amount or Decimal("0.00")
            if reward > 0:
                request.user.credit_wallet(
                    amount=reward,
                    source="cashback_reward",
                    reference=f"REWARD-{reference}"
                )

            messages.success(request, f"Electricity payment successful! Token: {txn.token or 'Processing...'}")
        else:
            txn.status = "failed"
            txn.save(update_fields=["status"])
            error_msg = api_response.get("message", "Unknown error from provider")
            messages.error(request, f"Payment failed: {error_msg}")
    except Exception as e:
        print("CheapDataHub electricity error:", e)
        txn.status = "failed"
        txn.save(update_fields=["status"])
        messages.error(request, "Network error while processing payment")

    return redirect(reverse("payment_success") + f"?reference={reference}")

def payment_success(request):
    reference = request.GET.get("reference")
    txn = None
    if reference:
        if reference.startswith("WALLET-"):
            txn = WalletTransaction.objects.filter(reference=reference, status="success").first()
        elif reference.startswith("AIRTIME-"):
            txn = AirtimeTransaction.objects.filter(reference=reference, status="success").first()

    return render(
        request,
        "store/payment_successful.html",
        {"reference": reference, "txn": txn},
    )


# ==============================
# AUTH & OTP
# ==============================
def password_is_strong(password: str) -> bool:
    return (
        len(password) >= 8
        and re.search(r"[A-Z]", password)
        and re.search(r"[a-z]", password)
        and re.search(r"[0-9]", password)
        and re.search(r"[!@#$%^&*()_+=\-{}[\]:;\"'<>,.?/]", password)
    )


def send_otp(email: str, otp: str):
    send_mail(
        subject="ResultPin Verification Code",
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

        request.session["pending_user"] = {
            "email": email,
            "password": password,
            "otp": otp,
            "expires_at": int(time.time()) + 600,
            "attempts": 0,
            "resend_count": 0,
        }
        request.session.modified = True

        send_otp(email, otp)
        messages.success(request, "Verification code sent!")
        return redirect("verify_otp")

    return render(request, "store/register.html")


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

        user, created = User.objects.get_or_create(
            username=email,
            defaults={"email": email, "is_active": True}
        )
        user.set_password(password)
        user.save(update_fields=["password", "is_active"])

        login(request, user)
        messages.success(request, "Welcome! Account ready.")
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
    data.update({
        "otp": new_otp,
        "expires_at": int(time.time()) + 600,
        "resend_count": data["resend_count"] + 1,
        "attempts": 0,
    })
    request.session["pending_user"] = data
    request.session.modified = True

    send_otp(data["email"], new_otp)
    messages.success(request, "New code sent!")
    return redirect("verify_otp")


@csrf_protect
def custom_login(request):
    if request.method == "POST":
        email = request.POST.get("username", "").strip().lower()
        password = request.POST.get("password")

        if not email or not password:
            messages.error(request, "Email and password required.")
            return redirect("login")

        user = authenticate(request, username=email, password=password)
        if user:
            login(request, user)
            return redirect("home")

        messages.error(request, "Invalid credentials.")
        return redirect("login")

    return render(request, "store/login.html")


def custom_logout(request):
    logout(request)
    messages.success(request, "Logged out successfully.")
    return redirect("home")

## ==================================
# SERVICE DASHBOARD - Airtime/Data
# ===================================

def service_dashboard(request, slug):
    category = get_object_or_404(ServiceCategory, slug=slug, is_active=True)
    
    providers = ServiceProvider.objects.filter(
        category=category, is_active=True
    ).order_by('order')

    provider_id = request.GET.get("provider")
    selected_provider = None
    if provider_id:
        selected_provider = providers.filter(id=provider_id).first()

    # ONLY ServicePlan (airtime/data bundles)
    if selected_provider:
        plans = ServicePlan.objects.filter(
            provider=selected_provider, is_active=True
        ).select_related('provider')
    else:
        plans = ServicePlan.objects.filter(
            provider__category=category, is_active=True
        ).select_related('provider')

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
@login_required
def tv_dashboard(request):
    # Get the TV category
    category = get_object_or_404(ServiceCategory, slug="tv", is_active=True)

    # All active providers in TV category (DSTV, GOTV, etc.)
    providers = ServiceProvider.objects.filter(
        category=category,
        is_active=True
    ).order_by('order')

    # Selected provider from URL ?provider=123
    provider_id = request.GET.get("provider")
    selected_provider = None
    if provider_id:
        selected_provider = providers.filter(id=provider_id).first()

    # Fetch available plans — filtered by selected provider or all in category
    if selected_provider:
        plans = ServicePlan.objects.filter(
            provider=selected_provider,
            is_active=True
        ).select_related('provider')
    else:
        plans = ServicePlan.objects.filter(
            provider__category=category,
            is_active=True
        ).select_related('provider')

    context = {
        "category": category,
        "providers": providers,
        "plans": plans,
        "selected_provider": selected_provider,
    }

    return render(request, "store/tv_dashboard.html", context)


## ================================================================
# Tv Subscription
# ================================================================

@login_required
def electricity_dashboard(request):
    category = get_object_or_404(ServiceCategory, slug="electricity", is_active=True)
    providers = ServiceProvider.objects.filter(category=category, is_active=True).order_by('order')
    
    provider_id = request.GET.get("provider")
    selected_provider = None
    if provider_id:
        selected_provider = providers.filter(id=provider_id).first()

    context = {
        "category": category,
        "providers": providers,
        "selected_provider": selected_provider,
    }
    return render(request, "store/electricity_dashboard.html", context)


## ==================================================================
# Unified Payment Processor (handles airtime, data, cable, electricity)
# ===================================================================

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

def purchase_airtime(provider, provider_id, phone, amount):
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


def purchase_cable(plan_id, cardnumber, phone=""):
    print("=== HIT CHEAPDATA CABLE ENDPOINT ===")
    print("API URL:", f"{RESELLER_BASE_URL}/cable/purchase/")
    print("Plan ID:", plan_id)
    print("Cardnumber:", cardnumber)
    print("Phone:", phone or "N/A")

    payload = {
        "plan_id": plan_id,
        "cardnumber": cardnumber,
        "phone": phone
    }
    print("Sending payload:", payload)

    response = requests.post(
        f"{RESELLER_BASE_URL}/cable/purchase/",
        json=payload,
        headers=RESELLER_HEADERS,
        timeout=30,
    )

    print("HTTP Status:", response.status_code)
    print("CheapData response:", response.text)
    return response.json()



def purchase_electricity(disco_id, meter_number, amount, phone, meter_type):
    return requests.post(
        f"{RESELLER_BASE_URL}/electricity/purchase/",
        json={
            "disco_id": disco_id,
            "meter_number": meter_number,
            "amount": int(amount),
            "phone": phone,
            "meter_type": meter_type,
        },
        headers=RESELLER_HEADERS,
        timeout=30,
    ).json()


# ------------------------------
# BLOG & REVIEWS
# ------------------------------
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


