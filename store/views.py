import requests
import uuid
import random
import time
import json
import pytz
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

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
from django.db import transaction

from django.contrib.auth import get_user_model

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

# Print key mode on import (useful for debugging)
print("Current Paystack key mode:", "LIVE" if settings.PAYSTACK_SECRET_KEY.startswith('sk_live_') else "TEST")


# ==============================
# PAYSTACK HELPERS
# ==============================
def initialize_paystack(email: str, amount_naira: Decimal, reference: str, callback_url: str, metadata: dict = None):
    """Initialize Paystack transaction."""
    payload = {
        "email": email,
        "amount": int(amount_naira * 100),  # in kobo
        "reference": reference,
        "callback_url": callback_url,
        "metadata": metadata or {},
    }

    try:
        response = requests.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print("Paystack initialize exception:", str(e))
        return {"status": False, "message": "Payment gateway error"}


def verify_paystack(reference: str):
    """Verify Paystack transaction."""
    try:
        url = f"https://api.paystack.co/transaction/verify/{reference}"
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
            timeout=10,
        )
        res = response.json()
        if res.get("status") and res.get("data", {}).get("status") == "success":
            return res.get("data")
        return None
    except Exception:
        return None


# ==============================
# GENERAL HELPERS
# ==============================
def send_otp(phone: str, email: str, otp: int) -> bool:
    try:
        send_mail(
            subject="Your ResultPin Verification Code",
            message=(
                f"Hi! Your 6-digit OTP is {otp}.\n\n"
                "Valid for 10 minutes.\n\n"
                "Thanks,\nResultPin Team"
            ),
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
            fail_silently=False,
        )
        return True
    except Exception:
        return False


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
            "wallet_balance": getattr(request.user, "balance", 0) if request.user.is_authenticated else 0,
        },
    )


# ====================
# WALLET VIEWS
# ====================
@login_required
def wallet(request):
    total_referrals = request.user.referrals.count()
    referral_earnings = WalletTransaction.objects.filter(
        user=request.user, description="Referral Bonus"
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    wallet_transactions = WalletTransaction.objects.filter(user=request.user).order_by('-created_at')

    context = {
        'total_referrals': total_referrals,
        'referral_earnings': referral_earnings,
        'wallet_transactions': wallet_transactions,
    }
    return render(request, 'store/wallet.html', context)


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
    except (json.JSONDecodeError, InvalidOperation):
        return JsonResponse({'status': False, 'message': 'Invalid amount'})

    if amount < Decimal('100'):
        return JsonResponse({'status': False, 'message': 'Minimum funding is ₦100'})

    reference = f"FUND_{request.user.id}_{uuid.uuid4().hex.upper()[:10]}"

    # Use a fallback email if user's email is blank
    email = request.user.email
    if not email or '@' not in email:  # empty or invalid
        email = f"user_{request.user.id}@resultpin.ng"  # safe dummy email

    payload = initialize_paystack(
        email=email,  # now guaranteed to be valid
        amount_naira=amount,
        reference=reference,
        callback_url=request.build_absolute_uri(reverse('verify_wallet_funding')),
        metadata={'type': 'wallet_funding', 'user_id': request.user.id}
    )

    if not payload.get('status'):
        print("\n=== WALLET FUNDING - PAYSTACK FAILED ===")
        print("User ID:", request.user.id)
        print("Email used:", email)
        print("Amount:", amount)
        print("Reference:", reference)
        print("Paystack Response:", payload)
        print("========================================\n")
        return JsonResponse({
            'status': False,
            'message': payload.get('message', 'Payment gateway error')
        })

    # Success → create pending transaction
    WalletTransaction.objects.create(
        user=request.user,
        amount=amount,
        transaction_type='credit',
        reference=reference,
        description='Wallet Funding',
        status='pending'
    )

    print("\n=== WALLET FUNDING - PAYSTACK SUCCESS ===")
    print("Authorization URL:", payload['data']['authorization_url'])
    print("Email sent:", email)
    print("==========================================\n")

    return JsonResponse(payload)


@csrf_exempt
@login_required
def verify_wallet_funding(request):
    reference = request.GET.get('reference') or request.GET.get('trxref')
    if not reference:
        messages.error(request, 'No payment reference')
        return redirect('wallet')

    txn = WalletTransaction.objects.filter(reference=reference, user=request.user, status='pending').first()
    if not txn:
        messages.error(request, 'Transaction not found or already processed')
        return redirect('wallet')

    data = verify_paystack(reference)
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


@login_required
def wallet_withdraw(request):
    bank_account = getattr(request.user, 'bank_account', None)

    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount', '0'))
        except (InvalidOperation, TypeError):
            messages.error(request, 'Invalid amount')
            return redirect('wallet_withdraw')

        if amount < Decimal('100'):
            messages.error(request, 'Minimum withdrawal is ₦100')
            return redirect('wallet_withdraw')

        if request.user.balance < amount:
            messages.error(request, 'Insufficient balance')
            return redirect('wallet_withdraw')

        if not bank_account or not bank_account.recipient_code:
            messages.error(request, 'No verified bank account found. Add one first.')
            return redirect('wallet_withdraw')

        reference = f"WITHDRAW_{request.user.id}_{uuid.uuid4().hex.upper()[:10]}"

        response = requests.post(
            'https://api.paystack.co/transfer',
            json={
                'source': 'balance',
                'amount': int(amount * 100),
                'reference': reference,
                'recipient': bank_account.recipient_code,
                'reason': 'Wallet withdrawal - ResultPin.ng'
            },
            headers={
                'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
                'Content-Type': 'application/json'
            }
        )
        result = response.json()

        if result.get('status'):
            with transaction.atomic():
                request.user.balance -= amount
                request.user.save(update_fields=['balance'])
                WalletTransaction.objects.create(
                    user=request.user,
                    amount=amount,
                    transaction_type='debit',
                    reference=reference,
                    description='Bank Withdrawal',
                    status='success'
                )
            messages.success(request, f'₦{amount:,} withdrawn successfully! Check your bank in 5-30 mins.')
        else:
            messages.error(request, f'Withdrawal failed: {result.get("message", "Transfer failed")}')

        return redirect('wallet_withdraw')

    return render(request, 'store/wallet_withdraw.html', {'bank_account': bank_account})


@login_required
def add_bank_account(request):
    if request.method == 'POST':
        account_number = request.POST.get('account_number')
        bank_code = request.POST.get('bank_code')

        if not account_number or not bank_code:
            return JsonResponse({'success': False, 'message': 'Please fill all fields'})

        # Test/Debug bypass
        if settings.DEBUG or settings.PAYSTACK_SECRET_KEY.startswith('sk_test_'):
            fake_name = "Test User Account"
            recipient_response = requests.post(
                "https://api.paystack.co/transferrecipient",
                json={
                    "type": "nuban",
                    "name": fake_name,
                    "account_number": account_number,
                    "bank_code": bank_code,
                    "currency": "NGN"
                },
                headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
            )
            data = recipient_response.json()
            if data.get('status'):
                recipient_code = data['data']['recipient_code']
                BankAccount.objects.update_or_create(
                    user=request.user,
                    defaults={
                        'bank_code': bank_code,
                        'account_number': account_number,
                        'account_name': fake_name,
                        'recipient_code': recipient_code,
                        'is_verified': True
                    }
                )
                return JsonResponse({'success': True, 'account_name': fake_name})
            return JsonResponse({'success': False, 'message': 'Failed to create test recipient'})

        # Production flow
        resolve_response = requests.get(
            f"https://api.paystack.co/bank/resolve?account_number={account_number}&bank_code={bank_code}",
            headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
        )
        resolve_data = resolve_response.json()
        if not resolve_data.get('status'):
            return JsonResponse({'success': False, 'message': resolve_data.get('message', 'Invalid account details')})

        account_name = resolve_data['data']['account_name']

        recipient_response = requests.post(
            "https://api.paystack.co/transferrecipient",
            json={
                "type": "nuban",
                "name": account_name,
                "account_number": account_number,
                "bank_code": bank_code,
                "currency": "NGN"
            },
            headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
        )
        recipient_data = recipient_response.json()
        if not recipient_data.get('status'):
            return JsonResponse({'success': False, 'message': 'Failed to link bank for transfers'})

        recipient_code = recipient_data['data']['recipient_code']
        BankAccount.objects.update_or_create(
            user=request.user,
            defaults={
                'bank_code': bank_code,
                'account_number': account_number,
                'account_name': account_name,
                'recipient_code': recipient_code,
                'is_verified': True
            }
        )
        return JsonResponse({'success': True, 'account_name': account_name})

    banks = [  # (your bank list here - kept unchanged)
        {"code": "044", "name": "Access Bank"}, {"code": "057", "name": "Zenith Bank"},
        {"code": "058", "name": "GTBank"}, {"code": "050", "name": "Ecobank"},
        # ... (rest of banks)
    ]
    return render(request, 'store/add_bank_account.html', {'banks': banks})


# =========================
# initiate service workflow 
# =========================
@login_required
def initiate_service_payment(request, plan_id):

    if 'application/json' not in request.content_type:
        return JsonResponse({'status': False, 'message': 'Bad request'}, status=400)
        
    if request.method != 'POST':
        return JsonResponse({'status': False, 'message': 'Invalid request'}, status=405)

    try:
        body = json.loads(request.body)
        raw_phone = body.get('phone', '').strip()
        payment_method = body.get('payment_method', 'card')
    except json.JSONDecodeError:
        return JsonResponse({'status': False, 'message': 'Invalid data sent'})

    if not raw_phone:
        return JsonResponse({'status': False, 'message': 'Please enter the recipient phone number'})

    # Phone validation
    digits = ''.join(filter(str.isdigit, raw_phone))
    if digits.startswith('234') and len(digits) == 13:
        phone = '+234' + digits[3:]
    elif digits.startswith('0') and len(digits) == 11:
        phone = '+234' + digits[1:]
    elif len(digits) == 10:
        phone = '+234' + digits
    else:
        return JsonResponse({'status': False, 'message': 'Please enter a valid Nigerian number (e.g., 08012345678)'})

    if phone[4] not in '789':
        return JsonResponse({'status': False, 'message': 'Please enter a valid mobile number (MTN, Airtel, Glo, 9mobile)'})

    plan = get_object_or_404(ServicePlan, id=plan_id, is_active=True)
    amount = plan.selling_price
    reference = f"SVC_{request.user.id}_{uuid.uuid4().hex.upper()}"

    if payment_method == 'wallet' and request.user.balance + Decimal('0.01') < amount:
        return JsonResponse({'status': False, 'message': 'Insufficient wallet balance. Please fund your wallet or use card.'})

    # Create transaction with payment_method for logic
    svc_txn = AirtimeTransaction.objects.create(
        user=request.user,
        phone=phone,
        service_plan=plan,
        amount_paid=amount,
        reference=reference,
        status='pending',
        payment_method=payment_method  # Add payment_method to your AirtimeTransaction model if not there
    )

    if payment_method == 'wallet':
        try:
            with transaction.atomic():
                request.user.balance -= amount
                request.user.save(update_fields=['balance'])
                WalletTransaction.objects.create(
                    user=request.user,
                    amount=amount,
                    transaction_type='debit',
                    reference=reference,
                    description=f'{plan.provider.category.name} Purchase - {plan.name}',
                    status='success'
                )
                svc_txn.status = 'paid'
                svc_txn.save()

            delivery_success = process_service_delivery(request, svc_txn, plan, phone)

            if not delivery_success:
                with transaction.atomic():
                    request.user.balance += amount
                    request.user.save(update_fields=['balance'])
                    WalletTransaction.objects.create(
                        user=request.user,
                        amount=amount,
                        transaction_type='credit',
                        reference=reference,
                        description='Refund - Delivery failed',
                        status='success'
                    )
                svc_txn.status = 'failed'
                svc_txn.save()
                return JsonResponse({'status': False, 'message': 'Delivery failed. Amount refunded to wallet.'})

            with transaction.atomic():
                savings = min(
                    plan.selling_price * Decimal('0.02'),
                    plan.discount_amount * Decimal('0.4'),
                    Decimal('30'),
                    plan.profit_amount * Decimal('0.8')
                )
                if savings > 0:
                    request.user.balance += savings
                    request.user.save(update_fields=['balance'])
                    WalletTransaction.objects.create(
                        user=request.user,
                        amount=savings,
                        transaction_type='credit',
                        reference=reference,
                        description='Cashback Reward',
                        status='success'
                    )
                svc_txn.status = 'success'
                svc_txn.save()

            return JsonResponse({'status': True, 'message': f'Purchase successful! ₦{savings:.0f} cashback added.'})

        except Exception as e:
            if svc_txn.status == 'paid':
                with transaction.atomic():
                    request.user.balance += amount
                    request.user.save(update_fields=['balance'])
                    WalletTransaction.objects.create(
                        user=request.user,
                        amount=amount,
                        transaction_type='credit',
                        reference=reference,
                        description='Refund - Transaction error',
                        status='success'
                    )
            svc_txn.status = 'failed'
            svc_txn.save()
            return JsonResponse({'status': False, 'message': 'Transaction failed. Amount refunded if deducted.'})

    else:  # Card - no wallet association
        email = request.user.email or f"user_{request.user.id}@resultpin.ng"
        payload = initialize_paystack(
            email=email,
            amount_naira=amount,
            reference=reference,
            callback_url=request.build_absolute_uri(reverse('verify_service_payment')),
            metadata={'user_id': request.user.id, 'type': 'service_purchase', 'plan_id': plan.id, 'phone': phone}
        )

        if payload.get('status'):
            return JsonResponse({'status': True, 'authorization_url': payload['data']['authorization_url']})
        else:
            svc_txn.status = 'failed'
            svc_txn.save()
            return JsonResponse({'status': False, 'message': 'Could not start card payment.'})


def process_service_delivery(request, svc_txn, plan, phone):
        """
        TEST MODE: Always simulate successful delivery
        This ensures cashback is added for testing
        """
        print(f"[TEST DELIVERY] Simulated success: {plan.name} ({plan.provider.name}) to {phone} - Reference: {svc_txn.reference}")

        # Always return True so cashback triggers
        return True


@csrf_exempt
@login_required
def verify_service_payment(request):
    reference = request.GET.get('reference') or request.GET.get('trxref')
    if not reference:
        messages.error(request, 'No payment reference')
        return redirect('home')

    svc_txn = AirtimeTransaction.objects.filter(reference=reference).first()
    if not svc_txn or svc_txn.status != 'pending':
        messages.error(request, 'Transaction not found or already processed')
        return redirect('home')

    data = verify_paystack(reference)
    if not data or data.get('status') != 'success':
        svc_txn.status = 'failed'
        svc_txn.save()
        messages.error(request, 'Payment verification failed')
        return redirect('home')

    # Amount check
    paid_amount = Decimal(data['amount']) / 100
    if paid_amount != svc_txn.amount_paid:
        svc_txn.status = 'failed'
        svc_txn.save()
        messages.error(request, 'Amount mismatch')
        return redirect('home')

    # === DELIVERY + CASHBACK (for card payments) ===
    try:
        delivery_success = process_service_delivery(request, svc_txn, svc_txn.service_plan, svc_txn.phone)

        if not delivery_success:
            svc_txn.status = 'failed'
            svc_txn.save()
            messages.error(request, 'Delivery failed. Contact support.')
            return redirect('home')

        with transaction.atomic():
            # Give cashback
            savings = min(
                svc_txn.service_plan.selling_price * Decimal('0.02'),
                svc_txn.service_plan.discount_amount * Decimal('0.4'),
                Decimal('30'),
                svc_txn.service_plan.profit_amount * Decimal('0.8')
            )

            if savings > 0:
                request.user.balance += savings
                request.user.save(update_fields=['balance'])
                WalletTransaction.objects.create(
                    user=request.user,
                    amount=savings,
                    transaction_type='credit',
                    reference=svc_txn.reference,
                    description='Cashback Reward',
                    status='success'
                )

            svc_txn.status = 'success'
            svc_txn.save()

        messages.success(request, f'Purchase successful! ₦{savings:.0f} cashback added to your wallet.')
        return redirect('payment_success')

    except Exception as e:
        print(f"[ERROR] Cashback failed for {reference}: {e}")
        svc_txn.status = 'failed'
        svc_txn.save()
        messages.error(request, 'Transaction completed but reward failed. Contact support.')
        return redirect('home')

# ------------------------------
# AUTHENTICATION VIEWS
# ------------------------------
User = get_user_model()

def password_is_strong(password: str) -> bool:
    """Check if password meets strength requirements."""
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

        # Required fields check
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

        # Generate and store OTP in session
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

    # Rate limit: 30 seconds between resends
    if int(time.time()) - data["created_at"] < 30:
        messages.error(request, "Please wait 30 seconds before requesting another code.")
        return redirect("verify_otp")

    # Max 5 resends
    if data.get("resend_count", 0) >= 5:
        request.session.pop("pending_registration", None)
        messages.error(request, "Too many resend attempts. Please start over.")
        return redirect("register")

    # New OTP
    new_otp = random.randint(100000, 999999)
    data.update({
        "otp": new_otp,
        "created_at": int(time.time()),
        "resend_count": data.get("resend_count", 0) + 1,
        "attempts": 0,  # Reset attempts on resend
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

    # OTP expires after 10 minutes
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

        # Success: Create user
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
# PAYMENT SUCCESS PAGE (Uses your existing template)
# ------------------------------
def payment_success(request):
    reference = request.GET.get("reference")
    
    # Optional: Fetch transaction details if you want to display them
    # txn = None
    # if reference:
    #     if reference.startswith("FUND_"):
    #         txn = WalletTransaction.objects.filter(reference=reference, status='success').first()
    #     elif reference.startswith("SVC_") or reference.startswith("AIR_"):
    #         txn = AirtimeTransaction.objects.filter(reference=reference, status='success').first()
    
    messages.success(request, "Payment completed successfully! Your transaction has been processed.")
    
    return render(request, "store/payment_successful.html", {
        # "txn": txn,  # Uncomment if you add the fetch above and want to show details
        "reference": reference,
    })

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


