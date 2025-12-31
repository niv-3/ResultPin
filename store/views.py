import requests
import uuid
import random
import time
import json
import pytz
from datetime import datetime
from decimal import Decimal

from django.http import JsonResponse
from django.urls import reverse
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.mail import send_mail
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.views.decorators.csrf import csrf_protect
from django.db import transaction  # ← Added for atomic balance updates
from django.contrib.auth import get_user_model
import re

from .models import (
    Product,
    User,
    BlogPost,
    Review,
    HeroBanner,
    FAQ,
    ServiceCategory,
    ServiceProvider,
    ServicePlan,
    ExamTransaction,
    AirtimeTransaction,
    ServiceTransaction,
    WalletTransaction,
    Referral,
    BankAccount,  # ← New: for withdrawals
)


# ==============================
# PAYSTACK CONFIG
# ==============================
PAYSTACK_HEADERS = {
    "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
    "Content-Type": "application/json",
}


# ==============================
# PAYSTACK HELPERS (MUST BE DEFINED EARLY)
# ==============================
def verify_paystack(reference: str):
    """Verify a Paystack transaction. Returns data dict if successful, else None."""
    try:
        url = f"https://api.paystack.co/transaction/verify/{reference}"
        response = requests.get(url, headers=PAYSTACK_HEADERS, timeout=10)
        res = response.json()

        if not res.get("status"):
            return None

        data = res.get("data")
        if data.get("status") == "success":
            return data
        return None
    except Exception:
        return None


def initialize_paystack(email: str, amount_naira, reference: str, callback_url: str, metadata: dict = None):
    """Helper to initialize Paystack payment."""
    payload = {
        "email": email,
        "amount": int(Decimal(amount_naira) * 100),
        "reference": reference,
        "callback_url": callback_url,
        "metadata": metadata or {},
    }

    try:
        response = requests.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload,
            headers=PAYSTACK_HEADERS,
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        return {"status": False, "message": "Payment gateway error"}


# ==============================
# GENERAL HELPERS
# ==============================
def send_otp(phone: str, email: str, otp: int) -> bool:
    try:
        send_mail(
            subject="Your ResultPin Verification Code",
            message=(
                f"Hi! Your 6-digit OTP is {otp}.\n\n"
                "Valid for 10 minutes. Use it to complete registration.\n\n"
                "If you didn't request this, ignore this email.\n\n"
                "Thanks,\nResultPin Team"
            ),
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
            fail_silently=False,
        )
        return True
    except Exception:
        return False


def normalize_phone(phone: str) -> str:
    phone = phone.strip()
    if phone.startswith("+"):
        return phone
    if phone.startswith("0"):
        return "+234" + phone[1:]
    return "+234" + phone


# ==============================
# VIEWS
# ==============================
def home(request):
    hero = HeroBanner.objects.filter(page="home", is_active=True).first()
    products = Product.objects.filter(is_active=True)
    faq_list = FAQ.objects.filter(is_active=True)
    services = ServiceCategory.objects.filter(is_active=True).order_by("order")

    return render(
        request,
        "store/home.html",
        {
            "hero": hero,
            "products": products,
            "services": services,
            "faq_list": faq_list,
            "quantity_options": range(1, 11),
            "wallet_balance": getattr(request.user, "balance", 0),
        },
    )
# ====================
# WALLET DASHBOARD
# ====================
@login_required
def wallet(request):
    total_referrals = request.user.referrals.count()
    referral_earnings = WalletTransaction.objects.filter(
        user=request.user,
        description="Referral Bonus"
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    wallet_transactions = WalletTransaction.objects.filter(
        user=request.user
    ).order_by('-created_at')

    context = {
        'total_referrals': total_referrals,
        'referral_earnings': referral_earnings,
        'wallet_transactions': wallet_transactions,
    }
    return render(request, 'store/wallet.html', context)


# ====================
# FUND WALLET
# ====================
@login_required
def wallet_fund(request):
    return render(request, 'store/wallet_fund.html', {
        'paystack_public_key': settings.PAYSTACK_PUBLIC_KEY
    })

@login_required
@require_POST
def wallet_fund_init(request):
    try:
        data = json.loads(request.body)
        amount = Decimal(data.get('amount', '0'))
    except Exception:
        return JsonResponse({'status': False, 'message': 'Invalid amount'})

    if amount < Decimal('100'):
        return JsonResponse({'status': False, 'message': 'Minimum funding is ₦100'})

    reference = f"FUND_{request.user.id}_{uuid.uuid4().hex.upper()[:10]}"

    # Use YOUR existing helper
    payload = initialize_paystack(
        email=request.user.email,
        amount_naira=amount,
        reference=reference,
        callback_url=request.build_absolute_uri(reverse('verify_wallet_funding')),
        metadata={'type': 'wallet_funding', 'user_id': request.user.id}
    )

    if not payload.get('status'):
        return JsonResponse({'status': False, 'message': 'Failed to connect to payment gateway'})

    # Log pending transaction
    WalletTransaction.objects.create(
        user=request.user,
        amount=amount,
        transaction_type='credit',
        reference=reference,
        description='Wallet Funding',
        status='pending'
    )

    return JsonResponse(payload)  # Contains authorization_url, reference, etc.
@csrf_exempt
@login_required
def verify_wallet_funding(request):
    reference = request.GET.get('reference') or request.GET.get('trxref')
    if not reference:
        messages.error(request, 'No payment reference')
        return redirect('wallet')

    txn = WalletTransaction.objects.filter(
        reference=reference,
        user=request.user,
        status='pending'
    ).first()

    if not txn:
        messages.error(request, 'Transaction not found or already processed')
        return redirect('wallet')

    data = verify_paystack(reference)  # ← Your working helper

    if not data or data.get('status') != 'success':
        txn.status = 'failed'
        txn.save()
        messages.error(request, 'Payment verification failed')
        return redirect('wallet')

    paid_amount = Decimal(data['amount']) / 100
    if paid_amount != txn.amount:
        txn.status = 'failed'
        txn.save()
        messages.error(request, 'Amount mismatch detected')
        return redirect('wallet')

    with transaction.atomic():
        txn.status = 'success'
        txn.save()
        request.user.balance += txn.amount
        request.user.save()

    messages.success(request, f'Wallet funded successfully with ₦{txn.amount:,}')
    return redirect('wallet')


# ====================
# WITHDRAW TO BANK
# ====================
@login_required
def wallet_withdraw(request):
    if request.method == 'POST':
        amount = Decimal(request.POST.get('amount', '0'))

        if amount < Decimal('100'):
            messages.error(request, 'Minimum withdrawal is ₦100')
            return redirect('wallet')

        if request.user.balance < amount:
            messages.error(request, 'Insufficient wallet balance')
            return redirect('wallet')

        try:
            bank = BankAccount.objects.get(user=request.user, is_verified=True)
        except BankAccount.DoesNotExist:
            messages.error(request, 'Please add and verify a bank account first')
            return redirect('wallet')

        reference = f"WITHDRAW_{request.user.id}_{uuid.uuid4().hex.upper()[:10]}"

        # Initiate Paystack Transfer
        response = requests.post(
            'https://api.paystack.co/transfer',
            headers={
                'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
                'Content-Type': 'application/json'
            },
            json={
                'source': 'balance',
                'amount': int(amount * 100),
                'reference': reference,
                'recipient': bank.recipient_code,
                'reason': 'Wallet withdrawal'
            }
        )
        result = response.json()

        if result.get('status'):
            with transaction.atomic():
                request.user.balance -= amount
                request.user.save()
                WalletTransaction.objects.create(
                    user=request.user,
                    amount=amount,
                    transaction_type='debit',
                    reference=reference,
                    description='Bank Withdrawal',
                    status='success'
                )
            messages.success(request, f'₦{amount} withdrawal successful! Funds will arrive soon.')
        else:
            messages.error(request, 'Withdrawal failed. Please try again later.')
        return redirect('wallet')

    return render(request, 'store/wallet_withdraw.html')


# ====================
# SERVICE PAYMENT WITH WALLET SUPPORT
# ====================

# Example: Airtime purchase view (adapt for data, TV, etc.)
@login_required
def airtime_buy(request, plan_id):
    plan = get_object_or_404(ServicePlan, id=plan_id, is_active=True)

    if request.method == 'POST':
        phone = request.POST.get('phone')
        payment_method = request.POST.get('payment_method')  # 'wallet' or 'card'

        # Store temporarily in session
        request.session['pending_service'] = {
            'plan_id': plan.id,
            'phone': phone,
            'payment_method': payment_method
        }
        return redirect('initiate_service_payment')

    return render(request, 'store/airtime_buy.html', {'plan': plan})


@login_required
def initiate_service_payment(request):
    data = request.session.get('pending_service')
    if not data:
        messages.error(request, 'No pending purchase found')
        return redirect('home')

    plan = get_object_or_404(ServicePlan, id=data['plan_id'])
    amount = plan.selling_price
    payment_method = data['payment_method']
    phone = data.get('phone')

    reference = f"SVC_{request.user.id}_{uuid.uuid4().hex.upper()[:10]}"

    # Create transaction record
    svc_txn = AirtimeTransaction.objects.create(  # Or ServiceTransaction for others
        user=request.user,
        phone=phone,
        service_plan=plan,
        amount_paid=amount,
        reference=reference,
        status='pending'
    )

    if payment_method == 'wallet':
        with transaction.atomic():
            if request.user.balance < amount:
                svc_txn.status = 'failed'
                svc_txn.save()
                messages.error(request, 'Insufficient wallet balance')
                del request.session['pending_service']
                return redirect('wallet')

            request.user.balance -= amount
            request.user.save()

            WalletTransaction.objects.create(
                user=request.user,
                amount=amount,
                transaction_type='debit',
                reference=reference,
                description='Service Purchase',
                status='success'
            )

        # Proceed to delivery
        del request.session['pending_service']
        return process_service_delivery(request, svc_txn, plan, phone)

    else:  # Card payment
        payload = initialize_paystack(
            email=request.user.email,
            amount_naira=amount,
            reference=reference,
            callback_url=request.build_absolute_uri(reverse('verify_service_payment')),
            metadata={
                'user_id': request.user.id,
                'type': 'service',
                'plan_id': plan.id,
                'phone': phone
            }
        )

        if payload.get('status'):
            return redirect(payload['data']['authorization_url'])
        else:
            messages.error(request, 'Payment setup failed')
            return redirect('home')


@csrf_exempt
@login_required
def verify_service_payment(request):
    reference = request.GET.get('reference')
    if not reference:
        messages.error(request, 'Invalid payment')
        return redirect('home')

    # Find the pending transaction (adjust model if using ServiceTransaction)
    svc_txn = AirtimeTransaction.objects.filter(reference=reference, status='pending').first()
    if not svc_txn:
        messages.error(request, 'Transaction not found')
        return redirect('home')

    data = verify_paystack_transaction(reference)
    if not data or data.get('status') != 'success':
        svc_txn.status = 'failed'
        svc_txn.save()
        messages.error(request, 'Payment failed')
        return redirect('home')

    return process_service_delivery(request, svc_txn, svc_txn.service_plan, svc_txn.phone)


def process_service_delivery(request, svc_txn, plan, phone):
    try:
        # ← YOUR EXISTING VTU/API DELIVERY CODE HERE
        success = your_vtu_delivery_function(plan, phone, request.user)  # Replace with yours

        if not success:
            raise Exception("Delivery failed")

        with transaction.atomic():
            svc_txn.status = 'success'
            svc_txn.save()

            # === SAFE SAVINGS REWARD (Opay-style, protects profit) ===
            savings = min(
                plan.selling_price * Decimal('0.02'),        # 2% of paid amount
                plan.discount_amount * Decimal('0.4'),       # Max 40% of discount
                Decimal('30')                                # Cap at ₦30
            )
            # Never exceed 80% of your profit
            savings = min(savings, plan.profit_amount * Decimal('0.8'))

            if savings > 0:
                request.user.balance += savings
                request.user.save()

                WalletTransaction.objects.create(
                    user=request.user,
                    amount=savings,
                    transaction_type='credit',
                    reference=svc_txn.reference,
                    description='Savings from Discount',
                    status='success'
                )

        messages.success(request, f'Purchase successful! ₦{savings} savings added to your wallet.')
        return redirect('payment_success')

    except Exception as e:
        with transaction.atomic():
            svc_txn.status = 'failed'
            svc_txn.save()

            # Auto refund if paid with wallet
            if svc_txn.amount_paid and hasattr(svc_txn, 'user') and svc_txn.user:
                request.user.balance += svc_txn.amount_paid
                request.user.save()

                WalletTransaction.objects.create(
                    user=request.user,
                    amount=svc_txn.amount_paid,
                    transaction_type='credit',
                    reference=svc_txn.reference,
                    description='Refund for failed purchase',
                    status='success'
                )

        messages.error(request, 'Transaction failed. Amount refunded to wallet.')
        return redirect('home')

# ------------------------------
# AUTHENTICATION
# ------------------------------

User = get_user_model()


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
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password")
        password2 = request.POST.get("password2")

        # Basic validation
        if not all([first_name, last_name, email, password, password2]):
            messages.error(request, "All required fields must be filled.")
            return redirect("register")

        if password != password2:
            messages.error(request, "Passwords do not match.")
            return redirect("register")

        if not password_is_strong(password):
            messages.error(
                request,
                "Password must be at least 8 characters and include uppercase, lowercase, number, and symbol.",
            )
            return redirect("register")

        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, "An account with this email already exists.")
            return redirect("register")

        # Generate OTP
        otp = random.randint(100000, 999999)

        # Store ONLY in session (NOT DB)
        request.session["pending_registration"] = {
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": email,
            "password": password,  # temporary, hashed later
            "otp": otp,
            "created_at": int(time.time()),
            "attempts": 0,
        }

        # Send OTP (email/SMS)
        send_otp(phone, email, otp)

        messages.success(request, "OTP sent to your email.")
        return redirect("verify_otp")

    return render(request, "store/register.html")


def resend_otp(request):
    data = request.session.get("pending_registration")

    if not data:
        messages.error(request, "Session expired. Please register again.")
        return redirect("register")

    # Rate limit: 30 seconds
    if int(time.time()) - data["created_at"] < 30:
        messages.error(request, "Please wait before requesting another OTP.")
        return redirect("verify_otp")

    # Max resend limit
    if data.get("resend_count", 0) >= 5:
        request.session.pop("pending_registration", None)
        messages.error(request, "Too many OTP requests. Please start again.")
        return redirect("register")

    # Generate new OTP
    new_otp = random.randint(100000, 999999)

    data.update({
        "otp": new_otp,
        "created_at": int(time.time()),
        "resend_count": data.get("resend_count", 0) + 1,
        "attempts": 0,
    })

    request.session["pending_registration"] = data

    send_otp(data["phone"], data["email"], new_otp)

    messages.success(request, "A new OTP has been sent.")
    return redirect("verify_otp")



@csrf_protect
def verify_otp(request):
    data = request.session.get("pending_registration")

    if not data:
        messages.error(request, "Session expired. Please register again.")
        return redirect("register")

    # OTP expires after 10 minutes
    if int(time.time()) - data["created_at"] > 600:
        request.session.pop("pending_registration", None)
        messages.error(request, "OTP expired. Please register again.")
        return redirect("register")

    if request.method == "POST":
        otp_input = request.POST.get("otp", "").strip()

        if otp_input != str(data["otp"]):
            data["attempts"] += 1
            request.session["pending_registration"] = data

            if data["attempts"] >= 5:
                request.session.pop("pending_registration", None)
                messages.error(request, "Too many failed attempts. Start over.")
                return redirect("register")

            messages.error(request, "Invalid OTP.")
            return redirect("verify_otp")

        # ✅ OTP VERIFIED — NOW CREATE USER
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

        # Cleanup session
        request.session.pop("pending_registration", None)

        messages.success(request, "Account verified successfully!")
        return redirect("wallet")

    return render(request, "store/verify_otp.html")


def custom_login(request):
    if request.method == "POST":
        identifier = request.POST.get("username", "").strip()
        password = request.POST.get("password")

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
    messages.success(request, "Logged out successfully.")
    return redirect("home")


@login_required
def wallet(request):
    # Wallet transactions
    transactions = WalletTransaction.objects.filter(
        user=request.user
    ).order_by("-created_at")[:20]

    # Referrals
    total_referrals = Referral.objects.filter(
        referrer=request.user
    ).count()

    referral_earnings = Referral.objects.filter(
        referrer=request.user,
        paid=True
    ).aggregate(
        total=Sum("amount_earned")
    )["total"] or 0

    context = {
        "transactions": transactions,
        "total_referrals": total_referrals,
        "referral_earnings": referral_earnings,
    }

    return render(request, "store/wallet.html", context)


# ------------------------------
# SERVICES
# ------------------------------
def service_dashboard(request, slug):
    category = get_object_or_404(ServiceCategory, slug=slug, is_active=True)
    providers = ServiceProvider.objects.filter(category=category, is_active=True)

    provider_id = request.GET.get("provider")
    plans = ServicePlan.objects.none()
    if provider_id:
        try:
            provider_id = int(provider_id)  # ← THIS LINE FIXES IT: convert to int
            plans = ServicePlan.objects.filter(provider_id=provider_id, is_active=True).select_related("provider")
        except (ValueError, TypeError):
            plans = ServicePlan.objects.none()  # invalid ID → no plans

    return render(
        request,
        "store/service_dashboard.html",
        {
            "category": category,
            "providers": providers,
            "plans": plans,
            "selected_provider": provider_id,  # now it's int or None
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
            #"PAYSTACK_PUBLIC_KEY":settings.pk_test_dc6959e07821e0c96082a88b21fd63f5a690a1f2,
        },
    )


# ------------------------------
# PAYMENT FLOWS
# ------------------------------
@csrf_exempt
@require_POST
def initiate_service_payment(request, plan_id):
    plan = get_object_or_404(ServicePlan, id=plan_id, is_active=True)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"status": False, "message": "Invalid JSON"})

    phone = normalize_phone(data.get("phone", "").strip())
    if not phone:
        return JsonResponse({"status": False, "message": "Phone number required"})

    reference = f"AIR_{plan.id}_{int(time.time())}_{uuid.uuid4().hex[:6].upper()}"
    amount_kobo = int(plan.selling_price * 100)

    email = request.user.email if request.user.is_authenticated and request.user.email else "customer@resultpin.ng"

    # Create pending transaction
    txn = AirtimeTransaction.objects.create(
        user=request.user if request.user.is_authenticated else None,
        phone=phone,
        service_plan=plan,
        amount_paid=plan.selling_price,
        reference=reference,
        status="pending",
    )

    payload = initialize_paystack(
        email=email,
        amount_naira=plan.selling_price,
        reference=reference,
        callback_url=request.build_absolute_uri(reverse("verify_service_payment")),
        metadata={"phone": phone, "plan_id": plan.id, "type": "airtime"},
    )

    if payload.get("status"):
        return JsonResponse(payload)

    # Cleanup on failure
    AirtimeTransaction.objects.filter(reference=reference).delete()
    return JsonResponse({"status": False, "message": payload.get("message", "Initialization failed")})


def verify_service_payment(request):
    reference = request.GET.get("reference") or request.GET.get("trxref")
    if not reference:
        messages.error(request, "No payment reference found.")
        return redirect("home")

    # Find transaction
    txn = None
    if reference.startswith("AIR_"):
        txn = AirtimeTransaction.objects.filter(reference=reference).first()
    if not txn:
        txn = ExamTransaction.objects.filter(reference=reference).first()

    if not txn:
        messages.error(request, "Transaction not found.")
        return redirect("home")

    expected_amount = txn.amount_paid

    # Verify with Paystack
    paystack_data = verify_paystack(reference)

    if not paystack_data:
        txn.status = "failed"
        txn.save()
        messages.error(request, "Payment verification failed.")
        return redirect("home")

    # Amount check
    paid_amount = Decimal(paystack_data["amount"]) / 100
    if paid_amount != expected_amount:
        txn.status = "failed"
        txn.save()
        messages.error(request, "Payment amount mismatch.")
        return redirect("home")

    # Mark as success only once
    if txn.status != "success":
        txn.status = "success"
        txn.save()

    messages.success(request, "Payment successful! Service will be delivered shortly.")
    return redirect(reverse("payment_success") + f"?reference={reference}")


    # ------------------------------
# PAYMENT SUCCESS PAGE
# ------------------------------
def payment_success(request):
    reference = request.GET.get("reference")
    if not reference:
        return redirect("home")

    if reference.startswith("AIR_"):
        txn = get_object_or_404(AirtimeTransaction, reference=reference, status="success")
    else:
        txn = get_object_or_404(ExamTransaction, reference=reference, status="success")

    return render(request, "store/payment_successful.html", {"txn": txn})


# ------------------------------
# BLOG & REVIEWS (keep these at the very end)
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
    name = request.POST.get("name")
    email = request.POST.get("email")
    rating = request.POST.get("rating")
    comment = request.POST.get("comment", "").strip()
    location = request.POST.get("location", "")

    if not rating or not comment:
        messages.error(request, "Rating and comment are required.")
        return redirect("home")

    if not request.user.is_authenticated and (not name or not email):
        messages.error(request, "Name and email required for guest reviews.")
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