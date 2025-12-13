import requests
import uuid
import random
import time
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

# Paystack headers
PAYSTACK_HEADERS = {
    "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
    "Content-Type": "application/json"
}

# -------------------------
# Helper: Send OTP via email
# -------------------------
def send_otp(phone, email, otp):
    try:
        send_mail(
            subject="Your ResultPin Verification Code",
            message=f"Hi! Your 6-digit OTP is {otp}.\n\n"
                    "Valid for 10 minutes. Use it to complete registration.\n\n"
                    "If you didn't request this, ignore this email.\n\nThanks, ResultPin Team",
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
            fail_silently=False,
        )
        print(f"OTP sent to {email}: {otp}")
        return True
    except Exception as e:
        print(f"Failed to send OTP → {e}")
        return False

# -------------------------
# Helper: normalize phone
# -------------------------
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
    context = {
        'products': products,
        'paystack_public_key': settings.PAYSTACK_PUBLIC_KEY,
    }
    return render(request, 'store/home.html', context)

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
            "otp_attempts": 0
        }

        if send_otp(phone, email, otp):
            messages.success(request, f"OTP sent to {email}.")
            return redirect("verify_otp")
        else:
            request.session.pop("reg_data", None)
            messages.error(request, "Failed to send OTP. Try again.")
            return redirect("register")

    return render(request, "store/register.html")

def verify_otp(request):
    if request.method == "POST":
        otp_input = request.POST.get("otp", "").strip()
        data = request.session.get("reg_data")

        if not data:
            messages.error(request, "Session expired. Please register again.")
            return redirect("register")

        now_ts = int(time.time())
        otp_age = now_ts - data.get("otp_created_at", now_ts)
        if otp_age > 10 * 60:
            request.session.pop("reg_data", None)
            messages.error(request, "OTP expired. Please register again.")
            return redirect("register")

        if otp_input != str(data.get("otp")):
            data["otp_attempts"] = data.get("otp_attempts", 0) + 1
            request.session["reg_data"] = data
            if data["otp_attempts"] >= 5:
                request.session.pop("reg_data", None)
                messages.error(request, "Too many incorrect OTP attempts. Please register again.")
                return redirect("register")
            messages.error(request, "Incorrect OTP. Try again.")
            return redirect("verify_otp")

        # Create user
        try:
            user = User.objects.create_user(
                username=data["email"],
                email=data["email"],
                phone=data["phone"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                password=data["password"],
                is_active=True
            )
        except Exception as e:
            request.session.pop("reg_data", None)
            messages.error(request, f"Could not create account: {str(e)}")
            return redirect("register")

        login(request, user)
        request.session.pop("reg_data", None)
        messages.success(request, "Account created & verified! Welcome!")
        return redirect("dashboard")

    return render(request, "store/verify_otp.html")

def resend_otp(request):
    data = request.session.get("reg_data")
    if not data:
        messages.error(request, "Session expired. Please register again.")
        return redirect("register")

    COOLDOWN = 30
    MAX_RESENDS = 5
    now_ts = int(time.time())

    if now_ts - data.get("otp_created_at", 0) < COOLDOWN:
        wait = COOLDOWN - (now_ts - data.get("otp_created_at", 0))
        messages.error(request, f"Please wait {wait}s before requesting a new OTP.")
        return redirect("verify_otp")

    if data.get("resend_count", 0) >= MAX_RESENDS:
        request.session.pop("reg_data", None)
        messages.error(request, "Too many resend attempts. Please register again.")
        return redirect("register")

    new_otp = random.randint(100000, 999999)
    data["otp"] = new_otp
    data["otp_created_at"] = now_ts
    data["resend_count"] = data.get("resend_count", 0) + 1
    data["otp_attempts"] = 0
    request.session["reg_data"] = data

    if send_otp(data["phone"], data["email"], new_otp):
        messages.success(request, "A new OTP has been sent to your email.")
    else:
        messages.error(request, "Failed to resend OTP. Try again later.")

    return redirect("verify_otp")

# ==============================
# LOGIN / LOGOUT
# ==============================
def custom_login(request):
    if request.method == "POST":
        identifier = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        if not identifier or not password:
            messages.error(request, "Please provide both email/phone and password.")
            return redirect("login")

        user_obj = User.objects.filter(Q(email__iexact=identifier) | Q(phone=identifier)).first()
        if not user_obj:
            messages.error(request, "Invalid login details.")
            return redirect("login")

        auth_user = authenticate(request, username=user_obj.username, password=password)
        if auth_user:
            if not auth_user.is_active:
                messages.error(request, "Account inactive or not verified.")
                return redirect("login")
            login(request, auth_user)
            return redirect("dashboard")

        messages.error(request, "Invalid credentials.")
        return redirect("login")

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
    total_referrals = User.objects.filter(referred_by=request.user).count()
    referral_earnings = total_referrals * 150
    return render(request, "store/dashboard.html", {
        "referral_earnings": referral_earnings,
        "total_referrals": total_referrals
    })
import requests
import uuid
import random
import time
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.contrib import messages
from django.core.mail import send_mail
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.db.models import Q
from .models import Product, Transaction, Vendor, User

# Paystack headers
PAYSTACK_HEADERS = {
    "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
    "Content-Type": "application/json"
}

# -----------------------
# Helper: send OTP (email)
# -----------------------
def send_otp(phone, email, otp):
    try:
        send_mail(
            subject="Your ResultPin Verification Code",
            message=(f"Hi! Your 6-digit OTP is {otp}.\n\n"
                     "Valid for 10 minutes. Use it to complete registration.\n\n"
                     "If you didn't request this, ignore this email.\n\nThanks, ResultPin Team"),
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
            fail_silently=False,
        )
        print(f"EMAIL OTP sent to {email}: {otp}")
        return True
    except Exception as e:
        print(f"EMAIL OTP FAILED → {e}")
        return False

# -----------------------
# Helper: normalize phone
# -----------------------
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
    context = {
        'products': products,
        'paystack_public_key': settings.PAYSTACK_PUBLIC_KEY,
    }
    return render(request, 'store/home.html', context)

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

        if not (first_name and last_name and phone_raw and email and password and password2):
            messages.error(request, "Please fill in all required fields.")
            return redirect("register")

        if password != password2:
            messages.error(request, "Passwords do not match.")
            return redirect("register")

        phone = normalize_phone(phone_raw)

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already exists")
            return redirect("register")

        if User.objects.filter(phone=phone).exists():
            messages.error(request, "Phone already exists")
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
            "resend_count": 0
        }

        sent = send_otp(phone, email, otp)
        if sent:
            messages.success(request, f"OTP sent to {email}.")
            return redirect("verify_otp")
        else:
            request.session.pop("reg_data", None)
            messages.error(request, "Failed to send OTP. Try again or contact support.")
            return redirect("register")

    return render(request, "store/register.html")

def verify_otp(request):
    if request.method == "POST":
        otp_input = request.POST.get("otp", "").strip()
        data = request.session.get("reg_data")

        if not data:
            messages.error(request, "Session expired. Please register again.")
            return redirect("register")

        now_ts = int(time.time())
        otp_age = now_ts - data.get("otp_created_at", now_ts)
        if otp_age > 10 * 60:
            request.session.pop("reg_data", None)
            messages.error(request, "OTP expired. Please register again.")
            return redirect("register")

        if otp_input != str(data.get("otp")):
            attempts = data.get("otp_attempts", 0) + 1
            data["otp_attempts"] = attempts
            request.session["reg_data"] = data
            if attempts >= 5:
                request.session.pop("reg_data", None)
                messages.error(request, "Too many incorrect OTP attempts. Please register again.")
                return redirect("register")
            messages.error(request, "Incorrect OTP. Try again.")
            return redirect("verify_otp")

        try:
            user = User.objects.create_user(
                username=data["email"],
                email=data["email"],
                phone=data["phone"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                password=data["password"],
                is_active=True,
            )
        except Exception as e:
            request.session.pop("reg_data", None)
            messages.error(request, f"Could not create account: {str(e)}")
            return redirect("register")

        login(request, user)
        request.session.pop("reg_data", None)
        messages.success(request, "Account created & verified! Welcome!")
        return redirect("dashboard")

    return render(request, "store/verify_otp.html")

def resend_otp(request):
    data = request.session.get("reg_data")
    if not data:
        messages.error(request, "Session expired. Please register again.")
        return redirect("register")

    COOLDOWN_SECONDS = 30
    MAX_RESENDS = 5
    now_ts = int(time.time())
    last_sent = data.get("otp_created_at", 0)
    resend_count = data.get("resend_count", 0)

    if now_ts - last_sent < COOLDOWN_SECONDS:
        wait = COOLDOWN_SECONDS - (now_ts - last_sent)
        messages.error(request, f"Please wait {wait}s before requesting a new OTP.")
        return redirect("verify_otp")

    if resend_count >= MAX_RESENDS:
        request.session.pop("reg_data", None)
        messages.error(request, "Too many resend attempts. Please register again.")
        return redirect("register")

    new_otp = random.randint(100000, 999999)
    data["otp"] = new_otp
    data["otp_created_at"] = now_ts
    data["resend_count"] = resend_count + 1
    data["otp_attempts"] = 0
    request.session["reg_data"] = data

    sent = send_otp(data["phone"], data["email"], new_otp)
    if sent:
        messages.success(request, "A new OTP has been sent to your email.")
    else:
        messages.error(request, "Failed to resend OTP. Try again later.")

    return redirect("verify_otp")

# ==============================
# LOGIN / LOGOUT
# ==============================
def custom_login(request):
    if request.method == 'POST':
        identifier = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        if not identifier or not password:
            messages.error(request, "Please provide both username (email/phone) and password.")
            return redirect('login')

        try:
            user_obj = User.objects.filter(Q(email__iexact=identifier) | Q(phone=identifier)).first()
        except Exception:
            user_obj = None

        if not user_obj:
            messages.error(request, "Invalid login details.")
            return redirect('login')

        auth_user = authenticate(request, username=user_obj.username, password=password)

        if auth_user:
            if not auth_user.is_active:
                messages.error(request, "Account not verified or inactive.")
                return redirect('login')

            login(request, auth_user)
            return redirect('dashboard')

        messages.error(request, "Invalid credentials. Please check your password.")
        return redirect('login')

    return render(request, 'store/login.html')

def custom_logout(request):
    logout(request)
    messages.success(request, "Logged out successfully")
    return redirect('home')

# ==============================
# DASHBOARD
# ==============================
@login_required
def dashboard(request):
    total_referrals = User.objects.filter(referred_by=request.user).count()
    referral_earnings = total_referrals * 150
    return render(request, 'store/dashboard.html', {
        'referral_earnings': referral_earnings,
        'total_referrals': total_referrals
    })

# ==============================
# PAYSTACK PAYMENT (unchanged)
# ==============================
@csrf_protect
def initiate_payment(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_active=True)
    
    if request.method == "POST":
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()

        if not email or not phone:
            messages.error(request, "Please provide both email and phone number.")
            return redirect('home')

        amount_ngk = int(product.sell_price * 100)
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
            "amount": amount_ngk,
            "reference": reference,
            "callback_url": request.build_absolute_uri('/payment-success/'),
            "metadata": {
                "product_id": product.id,
                "phone": phone,
                "email": email
            }
        }

        try:
            response = requests.post(
                "https://api.paystack.co/transaction/initialize",
                json=payload,
                headers=PAYSTACK_HEADERS,
                timeout=10
            )
            data = response.json()
            if data.get('status') and 'authorization_url' in data['data']:
                return redirect(data['data']['authorization_url'])
            else:
                messages.error(request, f"Payment failed: {data.get('message', 'Try again')}")
        except Exception as e:
            messages.error(request, f"Payment error: {str(e)}")

    return redirect('home')


@csrf_exempt
def payment_success(request):
    ref = request.GET.get('reference') or request.GET.get('trxref')
    if not ref:
        return redirect('home')

    try:
        response = requests.get(
            f"https://api.paystack.co/transaction/verify/{ref}",
            headers=PAYSTACK_HEADERS
        )
        data = response.json()

        if data.get('status') and data['data']['status'] == 'success':
            txn, created = Transaction.objects.get_or_create(
                reference=ref,
                defaults={
                    'user': request.user if request.user.is_authenticated else None,
                    'product': Product.objects.get(id=data['data']['metadata']['product_id']),
                    'amount_paid': Decimal(data['data']['amount']) / 100,
                    'profit': Decimal(data['data']['amount']) / 100,
                    'status': 'completed',
                    'payment_method': data['data']['channel']
                }
            )

            if not created:
                txn.status = 'completed'
                txn.payment_method = data['data']['channel']
                txn.save()

            product = txn.product
            phone = data['data']['metadata']['phone']
            email = data['data']['customer']['email']

            vendor = Vendor.objects.filter(is_active=True).order_by('priority').first()
            if vendor:
                epins_payload = {
                    "service": product.vendor_product_id,
                    "amount": str(int(product.buy_price)),
                    "reference": ref,
                    "phone": phone
                }
                epins_response = requests.post(
                    vendor.api_url,
                    json=epins_payload,
                    headers={"Authorization": f"Token {vendor.api_key}", "Content-Type": "application/json"}
                )
                epins_data = epins_response.json()
                if epins_data.get('status') == "success":
                    pin_token = epins_data['pin']
                    pin_serial = epins_data.get('serial', '')
                    txn.pin_token = pin_token
                    txn.pin_serial = pin_serial
                    txn.vendor_used = vendor
                    txn.save()

                    message = f"Your {product.name} e-PIN is {pin_token}. Check result at official portal. Thank you!"
                    try:
                        send_sms(phone, message)
                    except Exception:
                        print("send_sms failed or not defined in this module.")

                    send_mail(
                        f"Your {product.name} e-PIN",
                        message,
                        settings.EMAIL_HOST_USER,
                        [email],
                        fail_silently=True
                    )
                else:
                    messages.error(request, "PIN purchase failed. Contact support.")
            else:
                messages.error(request, "No vendor available.")

            return render(request, 'store/payment_success.html', {
                'txn': txn,
                'pin': txn.pin_token
            })
    except Exception as e:
        messages.error(request, f"Verification failed: {str(e)}")
        return redirect('home')
