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
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_POST
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth import get_user_model

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
)

from .paystack import initialize_paystack


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
@csrf_exempt
def paystack_webhook(request):
    # Verify signature
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

    # Parse payload
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    # Only care about successful charges
    if payload.get("event") != "charge.success":
        return HttpResponse("Ignored event", status=200)

    ref = payload.get("data", {}).get("reference")
    if not ref:
        return HttpResponse("No reference", status=200)

    # Find transaction
    try:
        txn = WalletTransaction.objects.get(reference=ref)
    except WalletTransaction.DoesNotExist:
        return HttpResponse("Unknown ref", status=200)

    # If already success → safe exit (this prevents 500 on retries)
    if txn.status == "success":
        return HttpResponse("Already processed", status=200)

    # Only update if pending
    if txn.status == "pending":
        try:
            with transaction.atomic():
                # Lock and re-check
                locked_txn = WalletTransaction.objects.select_for_update().get(reference=ref)
                if locked_txn.status == "pending":
                    locked_txn.status = "success"
                    locked_txn.save(update_fields=["status"])
        except WalletTransaction.DoesNotExist:
            pass  # Race condition — already handled by another call

    return HttpResponse("OK", status=200)

# ====================
# WALLET VIEWS
# ====================
@login_required
def wallet(request):
    user = request.user

    wallet_transactions = user.wallet_transactions.order_by("-created_at")

    referral_earnings = (
        user.wallet_transactions.filter(
            source="referral",
            transaction_type="credit",
            status="success",
        )
        .aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    total_referrals = user.total_referrals

    context = {
        "total_referrals": total_referrals,         
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
def wallet_fund_init(request):
    try:
        data = json.loads(request.body)
        amount = Decimal(data.get("amount", "0"))

        if amount < Decimal("100"):
            return JsonResponse({
                "status": False,
                "message": "Minimum funding amount is ₦100"
            })

        reference = f"WALLET-{uuid.uuid4().hex[:12].upper()}"

        # Create pending transaction — no credit yet
        WalletTransaction.objects.create(
            user=request.user,
            amount=amount,
            transaction_type="credit",
            source="funding",
            status="pending",
            reference=reference,
        )

        result = initialize_paystack(
            email=request.user.email,
            amount=amount,
            reference=reference,
            callback_url=request.build_absolute_uri(reverse("verify_wallet_funding")),
        )

        if not result.get("status"):
            return JsonResponse({
                "status": False,
                "message": result.get("message", "Payment initialization failed"),
            })

        return JsonResponse({
            "status": True,
            "data": {
                "authorization_url": result["data"]["authorization_url"]
            }
        })

    except Exception:
        return JsonResponse({
            "status": False,
            "message": "Unable to start payment"
        })


@login_required
def verify_wallet_funding(request):
    reference = request.GET.get("reference")
    if not reference:
        return redirect("wallet")

    headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
    response = requests.get(
        f"https://api.paystack.co/transaction/verify/{reference}",
        headers=headers,
        timeout=30
    )
    result = response.json()

    if not result.get("status") or result["data"]["status"] != "success":
        messages.error(request, "Payment verification failed.")
        return redirect("wallet")

    txn = WalletTransaction.objects.filter(reference=reference).first()
    if not txn:
        messages.error(request, "Transaction not found.")
        return redirect("wallet")

    if txn.status == "success":
        messages.info(request, "Payment already confirmed.")
    else:
        messages.success(request, "Wallet credited successfully!")

    return redirect("wallet")


@login_required
def wallet_withdraw(request):
    bank_account = getattr(request.user, "bank_account", None)

    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get("amount", "0"))
        except Exception:
            messages.error(request, "Invalid amount")
            return redirect("wallet_withdraw")

        if amount < Decimal("100"):
            messages.error(request, "Minimum withdrawal is ₦100")
            return redirect("wallet_withdraw")

        current_balance = request.user.wallet_balance
        if current_balance < amount:
            messages.error(request, "Insufficient balance")
            return redirect("wallet_withdraw")

        if not bank_account or not bank_account.recipient_code:
            messages.error(request, "No verified bank account found")
            return redirect("wallet_withdraw")

        reference = f"WITHDRAW_{request.user.id}_{uuid.uuid4().hex[:12]}"

        response = requests.post(
            "https://api.paystack.co/transfer",
            json={
                "source": "balance",
                "amount": int(amount * 100),
                "reference": reference,
                "recipient": bank_account.recipient_code,
                "reason": "Wallet withdrawal",
            },
            headers={
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        result = response.json()

        if not result.get("status"):
            messages.error(request, result.get("message", "Withdrawal failed"))
            return redirect("wallet_withdraw")

        # Record successful debit — balance auto-recalculates
        WalletTransaction.objects.create(
            user=request.user,
            amount=amount,
            transaction_type="debit",
            source="withdrawal",
            reference=reference,
            status="success",
        )

        messages.success(request, f"₦{amount:,} withdrawn successfully")
        return redirect("wallet")

    return render(request, "store/wallet_withdraw.html", {"bank_account": bank_account})


@login_required
def add_bank_account(request):
    # (unchanged — this part was correct)
    if request.method == "POST":
        account_number = request.POST.get("account_number")
        bank_code = request.POST.get("bank_code")

        if not account_number or not bank_code:
            return JsonResponse({"success": False, "message": "All fields required"})

        name = "Test Account" if settings.DEBUG else None

        if not settings.DEBUG:
            resolve = requests.get(
                f"https://api.paystack.co/bank/resolve?account_number={account_number}&bank_code={bank_code}",
                headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
                timeout=10,
            ).json()

            if not resolve.get("status"):
                return JsonResponse({"success": False, "message": "Invalid account"})
            name = resolve["data"]["account_name"]

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
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

@login_required
@require_POST
def initiate_service_payment(request, plan_id):
    try:
        data = json.loads(request.body)
        phone = data.get("phone")
        payment_method = data.get("payment_method")
        if not phone or payment_method not in ["wallet", "card"]:
            return JsonResponse({"status": False, "message": "Invalid data"})
        plan = get_object_or_404(ServicePlan, id=plan_id, is_active=True)
        amount = plan.selling_price
        if amount <= 0:
            return JsonResponse({"status": False, "message": "Invalid amount"})
        user = request.user
        reference = f"AIRTIME-{uuid.uuid4().hex[:12].upper()}"
        # ======================
        # WALLET PAYMENT (instant)
        # ======================
        if payment_method == "wallet":
            if user.wallet_balance < amount:
                return JsonResponse({
                    "status": False,
                    "message": f"Insufficient balance. Need ₦{amount:,}, have ₦{user.wallet_balance:,}"
                })
            with transaction.atomic():
                user.debit_wallet(
                    amount=amount,
                    source="airtime_purchase",
                    reference=reference
                )
                AirtimeTransaction.objects.create(
                    user=user,
                    service_plan=plan,
                    phone=phone,
                    amount_paid=amount,
                    payment_method="wallet",
                    reference=reference,
                    status="success"
                )
                reward = plan.reward_amount or 0
                if reward > 0:
                    user.credit_wallet(
                        amount=reward,
                        source="cashback_reward",
                        reference=f"REWARD-{reference}"
                    )
            return JsonResponse({
                "status": True,
                "message": "Purchase successful!",
                "redirect_url": reverse("payment_success") + f"?reference={reference}"
            })
        # ======================
        # CARD / PAYSTACK PAYMENT
        # ======================
        else:
            # Clean up stale pendings
            stale_cutoff = timezone.now() - timedelta(minutes=30)
            WalletTransaction.objects.filter(
                user=user,
                source="airtime_purchase",
                status="pending",
                created_at__lt=stale_cutoff
            ).delete()
            # Only one pending at a time
            if WalletTransaction.objects.filter(
                user=user,
                source="airtime_purchase",
                status="pending"
            ).exists():
                return JsonResponse({
                    "status": False,
                    "message": "You have a pending airtime payment. Please complete it or wait a few minutes."
                })
            with transaction.atomic():
                if WalletTransaction.objects.filter(reference=reference, status="pending").exists():
                    return JsonResponse({"status": False, "message": "Already processing"})
                pending_txn = WalletTransaction.objects.create(
                    user=user,
                    amount=amount,
                    transaction_type="debit",
                    source="airtime_purchase",
                    reference=reference,
                    status="pending"
                )
                request.session[f"pending_airtime_{reference}"] = {
                    "plan_id": plan.id,
                    "phone": phone,
                    "amount": float(amount),
                    "txn_id": pending_txn.id,
                }
            result = initialize_paystack(
                email=user.email,
                amount=amount * 100,
                reference=reference,
                callback_url=request.build_absolute_uri(reverse('verify_service_payment'))
            )
            if not result.get("status"):
                with transaction.atomic():
                    WalletTransaction.objects.filter(reference=reference, status="pending").delete()
                    session_key = f"pending_airtime_{reference}"
                    if session_key in request.session:
                        del request.session[session_key]
                return JsonResponse({
                    "status": False,
                    "message": result.get("message") or "Payment failed"
                })
            return JsonResponse({
                "status": True,
                "authorization_url": result["data"]["authorization_url"]
            })
    except Exception as e:
        print("Error:", str(e))
        return JsonResponse({"status": False, "message": "Service unavailable"})


@login_required
def verify_service_payment(request):
    reference = request.GET.get("reference") or request.GET.get("trxref")
    if not reference:
        messages.error(request, "Invalid reference")
        return redirect("payment_success")

    # Verify with Paystack (redundant if webhook ran, but safe)
    url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
    except Exception as e:
        print("Paystack verify error:", e)
        messages.error(request, "Payment verification failed")
        return redirect("payment_success")

    if not result.get("status") or result.get("data", {}).get("status") != "success":
        messages.error(request, "Payment not successful")
        return redirect("payment_success")

    session_key = f"pending_airtime_{reference}"
    pending_data = request.session.get(session_key)

    if not pending_data:
        # Already processed (likely by webhook)
        return redirect(reverse("payment_success") + f"?reference={reference}")

    try:
        with transaction.atomic():
            already_processed = True
            try:
                txn = WalletTransaction.objects.select_for_update().get(
                    reference=reference,
                    status="pending",
                    user=request.user
                )
                txn.status = "success"
                txn.save(update_fields=["status"])
                already_processed = False
                print(f"Redirect marked {reference} as success")
            except WalletTransaction.DoesNotExist:
                print(f"Transaction {reference} already processed by webhook")

            # Deliver airtime if not already done
            if not AirtimeTransaction.objects.filter(reference=reference).exists():
                plan = ServicePlan.objects.get(id=pending_data["plan_id"])
                AirtimeTransaction.objects.create(
                    user=request.user,
                    service_plan=plan,
                    phone=pending_data["phone"],
                    amount_paid=pending_data["amount"],
                    payment_method="card",
                    reference=reference,
                    status="success"
                )
                print(f"Airtime delivered by redirect for {reference}")

            # === CASHBACK: Apply only if not already given ===
            reward = 0
            if pending_data:
                plan = ServicePlan.objects.get(id=pending_data["plan_id"])
                reward = plan.reward_amount or 0

            if reward > 0 and not WalletTransaction.objects.filter(
                reference=f"REWARD-{reference}",
                source="cashback_reward"
            ).exists():
                request.user.credit_wallet(
                    amount=reward,
                    source="cashback_reward",
                    reference=f"REWARD-{reference}"
                )
                print(f"REDIRECT APPLIED CASHBACK: ₦{reward} for {reference}")

            # Clean session
            if session_key in request.session:
                del request.session[session_key]

            messages.success(request, "Payment successful!" + (f" Cashback ₦{reward} added!" if reward > 0 else ""))

    except Exception as e:
        print("Verification error:", str(e))
        messages.error(request, "Error completing transaction")

    return redirect(reverse("payment_success") + f"?reference={reference}")


def payment_success(request):
    reference = request.GET.get("reference")
    txn = None
    if reference:
        if reference.startswith("FUND_"):
            txn = WalletTransaction.objects.filter(
                reference=reference, status="success"
            ).first()
        elif reference.startswith("AIRTIME-"):
            txn = AirtimeTransaction.objects.filter(
                reference=reference, status="success"
            ).first()
    if reference and not txn:
        messages.info(request, "Transaction already processed or not found.")
    else:
        messages.success(request, "Payment completed successfully.")
    return render(
        request,
        "store/payment_successful.html",
        {
            "reference": reference,
            "txn": txn,
        },
    )
# ------------------------------
# UTILITIES
# ------------------------------

def password_is_strong(password: str) -> bool:
    return (
        len(password) >= 8
        and re.search(r"[A-Z]", password)
        and re.search(r"[a-z]", password)
        and re.search(r"[0-9]", password)
        and re.search(r"[!@#$%^&*()_+=\-{}[\]:;\"'<>,.?/]", password)
    )

@csrf_protect
def register(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password")
        password2 = request.POST.get("password2")

        if password != password2:
            messages.error(request, "Passwords do not match.")
            return redirect("register")

        if not password_is_strong(password):
            messages.error(request, "Password is too weak.")
            return redirect("register")

        otp = str(random.randint(100000, 999999))

        request.session["pending_user"] = {
            "email": email,
            "password": password,
            "otp": otp,
            "created_at": int(time.time()),
            "attempts": 0,
            "resend_count": 0,
        }

        send_otp(None, email, otp)

        messages.success(request, "OTP sent to your email.")
        return redirect("verify_otp")

    return render(request, "store/register.html")





from django.core.mail import send_mail
from django.conf import settings

def send_otp(phone, email, otp):
    send_mail(
        "ResultPin Verification Code",
        f"Your OTP is {otp}. It expires in 10 minutes.",
        settings.DEFAULT_FROM_EMAIL,
        [email],
        fail_silently=False,
    )



# ------------------------------
# VERIFY OTP
# ------------------------------
@csrf_protect
def verify_otp(request):
    data = request.session.get("pending_user")

    if not data:
        messages.error(request, "Registration session expired.")
        return redirect("register")

    if time.time() - data["created_at"] > 600:
        request.session.pop("pending_user", None)
        messages.error(request, "OTP expired.")
        return redirect("register")

    if request.method == "POST":
        otp_input = request.POST.get("otp", "").strip()

        if otp_input != data["otp"]:
            data["attempts"] += 1
            request.session["pending_user"] = data

            if data["attempts"] >= 5:
                request.session.pop("pending_user", None)
                messages.error(request, "Too many failed attempts.")
                return redirect("register")

            messages.error(request, "Invalid OTP.")
            return redirect("verify_otp")

        user = User.objects.create_user(
            username=data["email"],
            email=data["email"],
            password=data["password"],
            is_active=True,
        )

        login(request, user)
        request.session.pop("pending_user", None)

        messages.success(request, "Account verified successfully.")
        return redirect("wallet")

    return render(request, "store/verify_otp.html")


# ------------------------------
# RESEND OTP
# ------------------------------

@csrf_protect
def resend_otp(request):
    data = request.session.get("pending_user")

    if not data:
        messages.error(request, "Session expired. Please register again.")
        return redirect("register")

    if time.time() - data["created_at"] < 30:
        messages.error(request, "Please wait before requesting a new code.")
        return redirect("verify_otp")

    resend_count = data.get("resend_count", 0)
    if resend_count >= 5:
        request.session.pop("pending_user", None)
        messages.error(request, "Too many attempts. Register again.")
        return redirect("register")

    otp = random.randint(100000, 999999)

    data.update({
        "otp": str(otp),
        "created_at": int(time.time()),
        "resend_count": resend_count + 1,
        "attempts": 0,
    })

    request.session["pending_user"] = data

    send_otp(data["phone"], data["email"], otp)

    messages.success(request, "New OTP sent.")
    return redirect("verify_otp")


 #------------------------------
# LOGIN
# ------------------------------

@csrf_protect
def custom_login(request):
    if request.method == "POST":
        email = request.POST.get("username", "").strip().lower()
        password = request.POST.get("password")

        if not email or not password:
            messages.error(request, "Please enter email and password.")
            return redirect("login")

        user = authenticate(request, username=email, password=password)

        if user:
            login(request, user)
            return redirect("wallet")

        messages.error(request, "Invalid login credentials.")
        return redirect("login")

    return render(request, "store/login.html")



def custom_logout(request):
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect("home")


# ------------------------------
# SERVICES & OTHER VIEWS (cleaned)
# ------------------------------
def service_dashboard(request, slug):
    category = get_object_or_404(ServiceCategory, slug=slug, is_active=True)
    providers = ServiceProvider.objects.filter(category=category, is_active=True)

    provider_id = request.GET.get("provider")
    plans = ServicePlan.objects.none()
    selected_provider = None

    if provider_id:
        try:
            selected_provider = int(provider_id)
            plans = ServicePlan.objects.filter(provider_id=selected_provider, is_active=True).select_related("provider")
        except (ValueError, TypeError):
            pass  # Invalid → show no plans

    return render(
        request,
        "store/service_dashboard.html",
        {
            "category": category,
            "providers": providers,
            "plans": plans,
            "selected_provider": selected_provider,
        },
    )


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


