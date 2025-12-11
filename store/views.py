import requests
import uuid
import random
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.contrib import messages
from django.core.mail import send_mail
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from .models import Product, Transaction, Vendor, User

# Paystack headers
PAYSTACK_HEADERS = {
    "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
    "Content-Type": "application/json"
}

def send_sms(phone, message):
    """Send SMS via Termii"""
    if not settings.TERMII_API_KEY:
        print(f"[TEST MODE] SMS to {phone}: {message}")
        return
    url = "https://api.ng.termii.com/api/sms/send"
    data = {
        "to": phone,
        "from": settings.TERMII_SENDER_ID,
        "sms": message,
        "type": "plain",
        "channel": "generic",
        "api_key": settings.TERMII_API_KEY,
    }
    try:
        requests.post(url, json=data, timeout=10)
    except:
        pass

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
    if request.method == 'POST':
        first_name = request.POST['first_name'].strip()
        last_name = request.POST['last_name'].strip()
        phone = request.POST['phone'].strip()
        email = request.POST['email'].strip().lower()
        password = request.POST['password']
        password2 = request.POST['password2']

        if password != password2:
            messages.error(request, "Passwords do not match!")
            return redirect('register')
        if User.objects.filter(phone=phone).exists():
            messages.error(request, "Phone number already registered!")
            return redirect('register')
        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already registered!")
            return redirect('register')

        # Generate OTP
        otp = random.randint(100000, 999999)
        request.session['user_data'] = {
            'first_name': first_name,
            'last_name': last_name,
            'phone': phone,
            'email': email,
            'password': make_password(password),
            'otp': otp,
            'otp_attempts': 0
        }

        # Send OTP
        send_sms(phone, f"Your ResultPin verification code is {otp}. Valid for 10 minutes.")
        messages.success(request, f"OTP successfully sent to {phone}")
        return redirect('verify_otp')

    return render(request, 'store/register.html')


def verify_otp(request):
    if request.method == 'POST':
        otp_entered = request.POST['otp'].strip()
        data = request.session.get('user_data')

        if not data:
            messages.error(request, "Session expired. Register again.")
            return redirect('register')

        if str(data['otp']) == otp_entered:
            user = User.objects.create_user(
                username=data['phone'],
                first_name=data['first_name'],
                last_name=data['last_name'],
                phone=data['phone'],
                email=data['email'],
                password=data['password'],
                is_active=True
            )
            login(request, user)
            del request.session['user_data']
            messages.success(request, "Account created & verified! Welcome!")
            return redirect('home')
        else:
            data['otp_attempts'] += 1
            request.session['user_data'] = data
            if data['otp_attempts'] >= 3:
                del request.session['user_data']
                messages.error(request, "Too many wrong attempts.")
                return redirect('register')
            messages.error(request, "Invalid OTP. Try again.")

    return render(request, 'store/verify_otp.html')


def resend_otp(request):
    data = request.session.get('user_data')
    if data and 'phone' in data:
        new_otp = random.randint(100000, 999999)
        data['otp'] = new_otp
        data['otp_attempts'] = 0
        request.session['user_data'] = data
        send_sms(data['phone'], f"Your new OTP is {new_otp}")
        messages.success(request, "New OTP sent!")
    return redirect('verify_otp')


# ==============================
# LOGIN / LOGOUT
# ==============================
def custom_login(request):
    if request.method == 'POST':
        identifier = request.POST.get('username', '').strip()  # <-- matches your form
        password = request.POST.get('password', '').strip()
        user = authenticate(request, username=identifier, password=password)
        if user and user.is_active:
            login(request, user)
            return redirect('dashboard')
        messages.error(request, "Invalid login or account not verified")
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
# PAYSTACK PAYMENT
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
                    'profit': Decimal(data['data']['amount']) / 100,  # approximate
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

            # Send PIN via vendor
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
                    send_sms(phone, message)
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