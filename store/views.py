import json
import uuid
import hmac
import hashlib
import requests
from decimal import Decimal

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
    # Verify Paystack signature
    paystack_signature = request.headers.get("x-paystack-signature")
    if not paystack_signature:
        return HttpResponse(status=400)

    computed_signature = hmac.new(
        key=settings.PAYSTACK_SECRET_KEY.encode(),
        msg=request.body,
        digestmod=hashlib.sha512,
    ).hexdigest()

    if not hmac.compare_digest(computed_signature, paystack_signature):
        return HttpResponse(status=400)

    payload = json.loads(request.body)
    event = payload.get("event")

    if event == "charge.success":
        reference = payload["data"].get("reference")

        try:
            with transaction.atomic():
                txn = WalletTransaction.objects.select_for_update().get(
                    reference=reference,
                    status="pending"
                )
                # No balance field — just mark as success
                # Balance will be auto-calculated from transactions
                txn.status = "success"
                txn.save(update_fields=["status"])

        except WalletTransaction.DoesNotExist:
            pass  # Already processed or invalid

    return HttpResponse(status=200)


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


# ------------------------------
# INITIATE SERVICE PAYMENT
# ------------------------------
@login_required
@require_POST
def initiate_service_payment(request, plan_id):
    try:
        data = json.loads(request.body)
        phone = data.get("phone")
        payment_method = data.get("payment_method")

        if not phone or payment_method not in ["wallet", "card"]:
            return JsonResponse({"status": False, "message": "Invalid request"})

        plan = get_object_or_404(ServicePlan, id=plan_id)
        amount = Decimal(plan.selling_price)
        user = request.user

        # ======================
        # WALLET PAYMENT
        # ======================
        if payment_method == "wallet":
            current_balance = user.wallet_balance
            if current_balance < amount:
                return JsonResponse({
                    "status": False,
                    "message": "Insufficient wallet balance"
                })

            with transaction.atomic():
                WalletTransaction.objects.create(
                    user=user,
                    amount=amount,
                    transaction_type="debit",
                    source="purchase",
                    reference=str(uuid.uuid4()),
                    description=f"{plan.name} purchase via wallet",
                    status="success"
                )

                AirtimeTransaction.objects.create(
                    user=user,
                    service_plan=plan,
                    phone=phone,
                    amount_paid=amount,
                    payment_method="wallet",
                    reference=str(uuid.uuid4()),
                    status="success"
                )

            return JsonResponse({
                "status": True,
                "message": "Purchase successful"
            })

        # ======================
        # CARD PAYMENT (PAYSTACK)
        # ======================
        reference = f"RP-{uuid.uuid4().hex[:12].upper()}"

        WalletTransaction.objects.create(
            user=user,
            amount=amount,
            transaction_type="debit",
            source="purchase",
            reference=reference,
            description=f"{plan.name} purchase via card",
            status="pending"
        )

        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "email": user.email,
            "amount": int(amount * 100),
            "reference": reference,
            "callback_url": request.build_absolute_uri("/payments/verify/"),
            "metadata": {
                "plan_id": plan.id,
                "user_id": user.id,
                "phone": phone,
            }
        }

        response = requests.post(
            "https://api.paystack.co/transaction/initialize",
            headers=headers,
            json=payload,
            timeout=30
        )

        res_data = response.json()

        if not res_data.get("status"):
            return JsonResponse({
                "status": False,
                "message": "Unable to initialize payment"
            })

        return JsonResponse({
            "status": True,
            "authorization_url": res_data["data"]["authorization_url"]
        })

    except Exception as e:
        return JsonResponse({
            "status": False,
            "message": "An error occurred"
        })


# ------------------------------
# PAYSTACK CALLBACK / VERIFY
# ------------------------------
@login_required
def verify_payment(request):
    reference = request.GET.get("reference")
    if not reference:
        return JsonResponse({"status": False, "message": "Missing reference"})

    headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
    response = requests.get(
        f"https://api.paystack.co/transaction/verify/{reference}",
        headers=headers,
        timeout=30
    )
    res_data = response.json()

    if not res_data.get("status") or res_data["data"]["status"] != "success":
        return JsonResponse({"status": False, "message": "Payment not successful"})

    metadata = res_data["data"].get("metadata", {})
    plan_id = metadata.get("plan_id")
    phone = metadata.get("phone")

    plan = get_object_or_404(ServicePlan, id=plan_id)
    amount = Decimal(plan.selling_price)

    with transaction.atomic():
        wallet_tx = WalletTransaction.objects.select_for_update().get(
            reference=reference,
            status="pending"
        )

        wallet_tx.status = "success"
        wallet_tx.save(update_fields=["status"])

        AirtimeTransaction.objects.create(
            user=wallet_tx.user,
            service_plan=plan,
            phone=phone,
            amount_paid=amount,
            payment_method="card",
            reference=reference,
            status="success"
        )

    return JsonResponse({
        "status": True,
        "message": "Payment verified successfully"
    })

# ------------------------------
# AUTHENTICATION VIEWS
# ------------------------------
User = get_user_model()


def password_is_strong(password: str) -> bool:
    if len(password) < 8:
        return False
    return all([
        bool(re.search(r"[A-Z]", password)),
        bool(re.search(r"[a-z]", password)),
        bool(re.search(r"[0-9]", password)),
        bool(re.search(r"[!@#$%^&*()_+=\-{}[\]:;\"'<>,.?/]", password)),
    ])


@csrf_protect
def register(request):
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password")
        password2 = request.POST.get("password2")

        if not all([first_name, last_name, phone, email, password, password2]):
            messages.error(request, "All fields are required.")
            return redirect("register")

        if password != password2:
            messages.error(request, "Passwords do not match.")
            return redirect("register")

        if not password_is_strong(password):
            messages.error(
                request,
                "Password must be at least 8 characters with uppercase, lowercase, number, and symbol."
            )
            return redirect("register")

        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, "An account with this email already exists.")
            return redirect("register")

        otp = random.randint(100000, 999999)
        request.session["pending_registration"] = {
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": email,
            "password": password,
            "otp": otp,
            "created_at": int(time.time()),
            "attempts": 0,
            "resend_count": 0,
        }

        send_otp(phone, email, otp)
        messages.success(request, "Verification code sent to your email.")
        return redirect("verify_otp")

    return render(request, "store/register.html")


def resend_otp(request):
    data = request.session.get("pending_registration")
    if not data:
        messages.error(request, "Session expired. Please register again.")
        return redirect("register")

    if int(time.time()) - data["created_at"] < 30:
        messages.error(request, "Please wait 30 seconds before requesting another code.")
        return redirect("verify_otp")

    if data.get("resend_count", 0) >= 5:
        request.session.pop("pending_registration", None)
        messages.error(request, "Too many resend attempts. Please start over.")
        return redirect("register")

    new_otp = random.randint(100000, 999999)
    data.update({
        "otp": new_otp,
        "created_at": int(time.time()),
        "resend_count": data.get("resend_count", 0) + 1,
        "attempts": 0,
    })
    request.session["pending_registration"] = data

    send_otp(data["phone"], data["email"], new_otp)
    messages.success(request, "New verification code sent.")
    return redirect("verify_otp")


@csrf_protect
def verify_otp(request):
    data = request.session.get("pending_registration")
    if not data:
        messages.error(request, "Session expired. Please register again.")
        return redirect("register")

    if int(time.time()) - data["created_at"] > 600:
        request.session.pop("pending_registration", None)
        messages.error(request, "Code expired. Please register again.")
        return redirect("register")

    if request.method == "POST":
        otp_input = request.POST.get("otp", "").strip()

        if otp_input != str(data["otp"]):
            data["attempts"] += 1
            request.session["pending_registration"] = data

            if data["attempts"] >= 5:
                request.session.pop("pending_registration", None)
                messages.error(request, "Too many failed attempts. Please start over.")
                return redirect("register")

            messages.error(request, "Invalid code. Please try again.")
            return redirect("verify_otp")

        user = User.objects.create_user(
            username=data["email"],
            email=data["email"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            phone=data["phone"],
            password=data["password"],
            is_active=True,
        )
        login(request, user)
        request.session.pop("pending_registration", None)

        messages.success(request, "Account created and verified successfully!")
        return redirect("wallet")

    return render(request, "store/verify_otp.html")


# ------------------------------
# PAYMENT SUCCESS PAGE
# ------------------------------
def payment_success(request):
    reference = request.GET.get("reference")
    txn = None

    if reference:
        if reference.startswith("FUND_"):
            txn = WalletTransaction.objects.filter(
                reference=reference, status="success"
            ).first()
        elif reference.startswith(("SVC_", "AIR_")):
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

def custom_login(request):
    if request.method == "POST":
        identifier = request.POST.get("username", "").strip().lower()
        password = request.POST.get("password")

        if not identifier or not password:
            messages.error(request, "Please enter both email/phone and password.")
            return redirect("login")

        user = User.objects.filter(Q(email__iexact=identifier) | Q(phone=identifier)).first()
        if not user:
            messages.error(request, "Invalid login details.")
            return redirect("login")

        auth_user = authenticate(request, username=user.username, password=password)
        if auth_user:
            login(request, auth_user)
            return redirect("wallet")

        messages.error(request, "Incorrect password.")
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


