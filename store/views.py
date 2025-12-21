import requests
import uuid
import random
import time
import json
from django.http import JsonResponse
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.contrib import messages
from django.core.mail import send_mail
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Q

from .models import Product, Transaction, Vendor, User


# ==============================
# PAYSTACK HEADERS
# ==============================
PAYSTACK_HEADERS = {
    "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
    "Content-Type": "application/json"
}

# ==============================
# HELPERS
# ==============================
def send_otp(phone, email, otp):
    try:
        send_mail(
            subject="Your ResultPin Verification Code",
            message=(
                f"Hi! Your 6-digit OTP is {otp}.\n\n"
                "Valid for 10 minutes. Use it to complete registration.\n\n"
                "If you didn't request this, ignore this email.\n\n"
                "Thanks, ResultPin Team"
            ),
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
            fail_silently=False,
        )
        return True
    except Exception:
        return False


def normalize_phone(phone):
    phone = phone.strip()
    if phone.startswith('+'):
        return phone
    if phone.startswith('0'):
        return '+234' + phone.lstrip('0')
    return '+234' + phone


# ==============================
# HOME
# ==============================
def home(request):
    products = Product.objects.filter(is_active=True)
    return render(request, 'store/home.html', {
        'products': products,
        'paystack_public_key': settings.PAYSTACK_PUBLIC_KEY,
    })


# ==============================
# REGISTER + OTP
# ==============================
def register(request):
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        phone_raw = request.POST.get("phone", "").strip()
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")

        if not all([first_name, last_name, phone_raw, email, password, password2]):
            messages.error(request, "Please fill in all required fields.")
            return redirect("register")

        if password != password2:
            messages.error(request, "Passwords do not match.")
            return redirect("register")

        phone = normalize_phone(phone_raw)

        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, "Email already exists.")
            return redirect("register")

        if User.objects.filter(phone=phone).exists():
            messages.error(request, "Phone already exists.")
            return redirect("register")

        otp = random.randint(100000, 999999)
        now_ts = int(time.time())

        request.session["reg_data"] = {
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": email,
            "password": password,
            "otp": otp,
            "otp_created_at": now_ts,
            "resend_count": 0,
            "otp_attempts": 0,
        }

        if send_otp(phone, email, otp):
            messages.success(request, f"OTP sent to {email}.")
            return redirect("verify_otp")

        request.session.pop("reg_data", None)
        messages.error(request, "Failed to send OTP.")
        return redirect("register")

    return render(request, "store/register.html")


def verify_otp(request):
    if request.method == "POST":
        otp_input = request.POST.get("otp", "").strip()
        data = request.session.get("reg_data")

        if not data:
            messages.error(request, "Session expired.")
            return redirect("register")

        if int(time.time()) - data["otp_created_at"] > 600:
            request.session.pop("reg_data", None)
            messages.error(request, "OTP expired.")
            return redirect("register")

        if otp_input != str(data["otp"]):
            data["otp_attempts"] += 1
            request.session["reg_data"] = data

            if data["otp_attempts"] >= 5:
                request.session.pop("reg_data", None)
                messages.error(request, "Too many attempts.")
                return redirect("register")

            messages.error(request, "Incorrect OTP.")
            return redirect("verify_otp")

        user = User.objects.create_user(
            username=data["email"],
            email=data["email"],
            phone=data["phone"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            password=data["password"],
            is_active=True
        )

        login(request, user)
        request.session.pop("reg_data", None)
        messages.success(request, "Account created & verified!")
        return redirect("dashboard")

    return render(request, "store/verify_otp.html")


def resend_otp(request):
    data = request.session.get("reg_data")
    if not data:
        return redirect("register")

    now = int(time.time())
    if now - data["otp_created_at"] < 30:
        messages.error(request, "Please wait before resending OTP.")
        return redirect("verify_otp")

    if data["resend_count"] >= 5:
        request.session.pop("reg_data", None)
        messages.error(request, "Too many resend attempts.")
        return redirect("register")

    data.update({
        "otp": random.randint(100000, 999999),
        "otp_created_at": now,
        "resend_count": data["resend_count"] + 1,
        "otp_attempts": 0
    })
    request.session["reg_data"] = data

    send_otp(data["phone"], data["email"], data["otp"])
    messages.success(request, "New OTP sent.")
    return redirect("verify_otp")


# ==============================
# LOGIN / LOGOUT
# ==============================
def custom_login(request):
    if request.method == "POST":
        identifier = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        user = User.objects.filter(
            Q(email__iexact=identifier) | Q(phone=identifier)
        ).first()

        if not user:
            messages.error(request, "Invalid login details.")
            return redirect("login")

        auth_user = authenticate(
            request, username=user.username, password=password
        )
        if not auth_user:
            messages.error(request, "Invalid credentials.")
            return redirect("login")

        login(request, auth_user)
        return redirect("dashboard")

    return render(request, "store/login.html")


def custom_logout(request):
    logout(request)
    messages.success(request, "Logged out successfully.")
    return redirect("home")


# ==============================
# DASHBOARD
# ==============================
@login_required
def dashboard(request):
    total_referrals = User.objects.filter(
        referred_by=request.user
    ).count()
    referral_earnings = total_referrals * 150

    return render(request, "store/dashboard.html", {
        "total_referrals": total_referrals,
        "referral_earnings": referral_earnings
    })


# ==============================
# PLACEHOLDER FOR INITIATE PAYMENT (JS handles actual flow)
# ==============================
@csrf_exempt
def initiate_payment(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_active=True)

    if request.method == "POST":
        try:
            data = json.loads(request.body)
            email = data.get('email', '').strip()
            phone = data.get('phone', '').strip()
        except Exception:
            return JsonResponse({"status": False, "message": "Invalid request."})

        if not email or not phone:
            return JsonResponse({"status": False, "message": "Email and phone required."})

        amount = int(product.sell_price * 100)
        reference = f"RES-{uuid.uuid4().hex[:12].upper()}"

        txn = Transaction.objects.create(
            user=request.user if request.user.is_authenticated else None,
            product=product,
            amount_paid=product.sell_price,
            profit=product.sell_price - product.buy_price,
            reference=reference,
            status='pending'
        )

        payload = {
            "email": email,
            "amount": amount,
            "reference": reference,
            "callback_url": request.build_absolute_uri('/payment-success/'),
            "metadata": {
                "product_id": product.id,
                "phone": phone,
            }
        }

        try:
            response = requests.post(
                "https://api.paystack.co/transaction/initialize",
                json=payload,
                headers=PAYSTACK_HEADERS,
                timeout=15
            )
            res_data = response.json()
        except Exception:
            return JsonResponse({"status": False, "message": "Payment initialization failed."})

        if res_data.get("status") and res_data.get("data"):
            return JsonResponse({
                "status": True,
                "authorization_url": res_data["data"]["authorization_url"]
            })

        return JsonResponse({"status": False, "message": res_data.get("message", "Payment init failed.")})

    return JsonResponse({"status": False, "message": "Invalid request method."})

# ==============================
# PAYMENT SUCCESS + VTPASS PIN
# ==============================
@csrf_exempt
def payment_success(request):
    ref = request.GET.get('reference') or request.GET.get('trxref')
    if not ref:
        return redirect('home')

    try:
        # Verify payment with Paystack
        response = requests.get(
            f"https://api.paystack.co/transaction/verify/{ref}",
            headers=PAYSTACK_HEADERS,
            timeout=10
        )
        data = response.json()

        if not (data.get('status') and data['data']['status'] == 'success'):
            messages.error(request, "Payment verification failed.")
            return redirect('home')

        txn = Transaction.objects.get(reference=ref)

        if txn.status != 'completed':
            txn.status = 'completed'
            txn.payment_method = data['data']['channel']
            txn.save()

        product = txn.product
        email = data['data']['customer']['email']
        phone = data['data']['metadata'].get('phone')

        # ================= VTPASS SANDBOX / LIVE =================
        if getattr(settings, "VTPASS_TEST_MODE", True):
            pin_token = f"TEST-WAEC-{random.randint(1000,9999)}"
            pin_serial = f"TEST-SERIAL-{random.randint(100000,999999)}"
        else:
            vtpass_url = "https://api.vtpass.com/api/pay"
            vtpass_payload = {
                "serviceID": product.vendor_product_id or "waec",
                "request_id": ref,
                "amount": int(product.buy_price),
                "phone": phone
            }

            vtpass_headers = {
                "apikey": settings.VTPASS_API_KEY,
                "secretkey": settings.VTPASS_SECRET_KEY,
                "Content-Type": "application/json"
            }

            vtpass_response = requests.post(
                vtpass_url,
                json=vtpass_payload,
                headers=vtpass_headers,
                timeout=20
            )

            vtpass_data = vtpass_response.json()

            if vtpass_data.get("code") != "000":
                messages.error(request, "PIN purchase failed. Please contact support.")
                return redirect('home')

            card = vtpass_data["content"]["cards"][0]
            pin_token = card["Pin"]
            pin_serial = card.get("Serial", "")

        # Save PIN info
        txn.pin_token = pin_token
        txn.pin_serial = pin_serial
        txn.save()

        # Send email
        send_mail(
            subject=f"Your {product.name} e-PIN",
            message=(
                f"Hello,\n\n"
                f"Your {product.name} e-PIN is:\n\n"
                f"{pin_token}\n\n"
                "Thank you for choosing ResultPin."
            ),
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
            fail_silently=True
        )

        return render(request, 'store/payment_successful.html', {
            'txn': txn,
            'pin': pin_token
        })

    except Exception as e:
        print("Payment success error:", e)
        return redirect('home')
