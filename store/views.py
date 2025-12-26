import requests
import uuid
import random
import time
import json
from datetime import datetime
import pytz
from decimal import Decimal
from django.http import JsonResponse

from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.contrib import messages
from django.core.mail import send_mail
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.views.decorators.http import require_POST
from .models import (
    Product,
    Transaction,
    Vendor,
    User,
    BlogPost,
    Review,
    HeroBanner,
    FAQ,
    ServiceCategory,
    ServiceProvider,
    ServicePlan,
)


# ==============================
# PAYSTACK HEADERS
# ==============================
PAYSTACK_HEADERS = {
    "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
    "Content-Type": "application/json"
}

# ==============================
# UI / UX CONTENT (BLOG + REVIEWS)  ✅ ADDED
# ==============================
def get_blog_posts():
    return [
        {
            "title": "How to Buy WAEC Result Checker PIN Online",
            "excerpt": "Learn how to safely and instantly purchase your WAEC result checker PIN online.",
            "author": "ResultPin Team",
            "date": "December 2025",
            "slug": "buy-waec-pin-online",
        },
        {
            "title": "Difference Between WAEC, NECO & JAMB",
            "excerpt": "A simple breakdown to help students and parents understand each exam body.",
            "author": "Education Desk",
            "date": "December 2025",
            "slug": "waec-neco-jamb-difference",
        },
        {
            "title": "Why ResultPin Is Trusted Nationwide",
            "excerpt": "Fast delivery, secure payment, and instant email confirmation.",
            "author": "Admin",
            "date": "December 2025",
            "slug": "why-resultpin-is-trusted",
        },
    ]


def get_customer_reviews():
    return [
        {"name": "Chinedu O.", "rating": 5, "comment": "Got my WAEC PIN instantly.", "location": "Lagos"},
        {"name": "Aisha M.", "rating": 5, "comment": "Very smooth payment process.", "location": "Abuja"},
        {"name": "Samuel K.", "rating": 4, "comment": "Fast delivery and email alert.", "location": "Port Harcourt"},
        {"name": "Blessing E.", "rating": 5, "comment": "Trusted platform. Highly recommended.", "location": "Enugu"},
    ]

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


def generate_request_id():
    lagos_tz = pytz.timezone('Africa/Lagos')
    now = datetime.now(lagos_tz)
    date_str = now.strftime("%Y%m%d%H%M")
    random_str = uuid.uuid4().hex[:7]
    return date_str + random_str

# ==============================
# HOME
# ==============================

def home(request):
    hero = HeroBanner.objects.filter(
        page="home",
        is_active=True
    ).first()

    products = Product.objects.filter(is_active=True)   # ✅ exams
    faq_list = FAQ.objects.filter(is_active=True)

    services = ServiceCategory.objects.filter(
        is_active=True
    ).order_by('order')   # ✅ airtime, data, tv, electricity

    return render(request, 'store/home.html', {
        'hero': hero,
        'products': products,     # exams section (UNCHANGED)
        'services': services,     # service cards
        'faq_list': faq_list,
        'quantity_options': range(1, 11),
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


def service_dashboard(request, slug):
    category = get_object_or_404(ServiceCategory, slug=slug, is_active=True)

    providers = ServiceProvider.objects.filter(
        category=category,
        is_active=True
    )

    plans = ServicePlan.objects.filter(
        provider__in=providers,
        is_active=True
    ).select_related('provider')

    return render(
        request,
        'store/service_dashboard.html',
        {
            'category': category,
            'providers': providers,
            'plans': plans
        }
    )



# ==============================
# INITIATE PAYMENT
# ==============================
@csrf_exempt
def initiate_payment(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_active=True)

    if request.method == "POST":
        if request.content_type == "application/json":
            try:
                data = json.loads(request.body)
                email = data.get('email', '').strip()
                phone = normalize_phone(data.get('phone', '').strip())
                quantity = int(data.get('quantity', 1))
            except Exception:
                return JsonResponse({"status": False, "message": "Invalid JSON."})
        else:
            email = request.POST.get('email', '').strip()
            phone = normalize_phone(request.POST.get('phone', '').strip())
            quantity = int(request.POST.get('quantity', 1))

        if not email or not phone:
            return JsonResponse({"status": False, "message": "Email and phone required."})

        amount = int(product.sell_price * quantity * 100)
        reference = f"RES-{uuid.uuid4().hex[:12].upper()}"

        txn = Transaction.objects.create(
            user=request.user if request.user.is_authenticated else None,
            product=product,
            amount_paid=product.sell_price * quantity,
            profit=(product.sell_price - product.buy_price) * quantity,
            reference=reference,
            quantity=quantity,
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
                "quantity": quantity
            }
        }

        response = requests.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload,
            headers=PAYSTACK_HEADERS,
            timeout=15
        )

        res_data = response.json()

        if res_data.get("status"):
            return JsonResponse({
                "status": True,
                "authorization_url": res_data["data"]["authorization_url"]
            })

        return JsonResponse({"status": False, "message": res_data.get("message")})

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
        phone = normalize_phone(data['data']['metadata'].get('phone'))
        quantity = int(data['data']['metadata'].get('quantity', 1))

        request_id = generate_request_id()
        pins_list = []

        for i in range(quantity):
            vtpass_response = requests.post(
                "https://sandbox.vtpass.com/api/pay",
                json={
                    "request_id": request_id,
                    "serviceID": product.vendor_product_id or "waec",
                    "amount": int(product.buy_price),
                    "phone": phone,
                    "quantity": 1
                },
                headers={
                    "apikey": settings.VTPASS_API_KEY,
                    "secretkey": settings.VTPASS_SECRET_KEY,
                    "Content-Type": "application/json"
                },
                timeout=20
            )

            vtpass_data = vtpass_response.json()

            if vtpass_data.get("code") != "000":
                continue

            card = vtpass_data["content"]["cards"][0]
            pins_list.append({
                "pin": card["Pin"],
                "serial": card.get("Serial", "")
            })

        if not pins_list:
            messages.error(request, "No pins generated.")
            return redirect('home')

        txn.pin_token = ",".join(p["pin"] for p in pins_list)
        txn.pin_serial = ",".join(p["serial"] for p in pins_list)
        txn.save()

        send_mail(
            subject=f"Your {product.name} e-PIN(s)",
            message="\n".join(p["pin"] for p in pins_list),
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
        )

        return render(request, 'store/payment_successful.html', {
            'txn': txn,
            'pins': pins_list
        })

    except Exception as e:
        messages.error(request, "Unexpected error.")
        return redirect('home')
@require_POST
@login_required
def submit_review(request):
    rating = request.POST.get("rating")
    comment = request.POST.get("comment")
    location = request.POST.get("location", "")

    if not rating or not comment:
        messages.error(request, "Rating and comment are required.")
        return redirect("home")

    Review.objects.create(
        name=request.user.get_full_name() or request.user.username,
        email=request.user.email,
        location=location,
        rating=int(rating),
        comment=comment,
    )

    return redirect("review_thank_you")


def review_thank_you(request):
    return render(request, "store/review_thank_you.html")


def blog_list(request):
    posts = BlogPost.objects.filter(published=True).order_by('-created_at')
    return render(request, "blog/blog_list.html", {   # ← Changed to blog/...
        "posts": posts
    })


def blog_detail(request, slug):
    post = get_object_or_404(BlogPost, slug=slug, published=True)
    return render(request, "blog/blog_detail.html", {   # ← Changed to blog/...
        "post": post
    })

    return render(request, "store/blog_detail.html", {
        "post": post
    })

def review_thank_you(request):
    return render(request, "store/review_thank_you.html")


def provider_plans(request, category, provider):
    banner = HeroBanner.objects.filter(
        page=category,
        is_active=True
    ).first()

    category_obj = ServiceCategory.objects.filter(
        slug=category,
        is_active=True
    ).first()

    provider_obj = None
    plans = []

    if category_obj:
        provider_obj = ServiceProvider.objects.filter(
            category=category_obj,
            name__iexact=provider,
            is_active=True
        ).first()

        if provider_obj:
            plans = ServicePlan.objects.filter(
                provider=provider_obj,
                is_active=True
            )

    return render(request, 'store/provider_plans.html', {
        'banner': banner,
        'category': category_obj,
        'provider': provider_obj,
        'plans': plans,
    })

