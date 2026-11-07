import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET

from .models import User


def google_enabled():
    client_id = settings.GOOGLE_OAUTH_CLIENT_ID.strip()
    secret = settings.GOOGLE_OAUTH_CLIENT_SECRET.strip()
    return client_id.endswith(".apps.googleusercontent.com") and bool(secret) and secret != "your_client_secret"


@require_GET
def start(request):
    if request.user.is_authenticated:
        return redirect("wallet")
    if not google_enabled():
        messages.error(request, "Google sign-in is currently unavailable.")
        return redirect("login")

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    callback = settings.GOOGLE_OAUTH_REDIRECT_URI or request.build_absolute_uri(reverse("google_callback"))
    next_url = request.GET.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = ""
    request.session["google_signin"] = {
        "next": next_url,
        "state": state, "verifier": verifier, "callback": callback, "expires_at": time.time() + 600,
    }
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID, "redirect_uri": callback,
        "response_type": "code", "scope": "openid email", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account",
    }
    return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@require_GET
def callback(request):
    if request.user.is_authenticated:
        return redirect("wallet")
    attempt = request.session.pop("google_signin", None)
    code = request.GET.get("code")
    if (
        not google_enabled() or not attempt or not code or attempt["expires_at"] < time.time()
        or not secrets.compare_digest(attempt["state"].encode(), request.GET.get("state", "").encode())
    ):
        messages.error(request, "Google sign-in expired or was cancelled. Please try again.")
        return redirect("login")

    try:
        token = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code, "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET, "redirect_uri": attempt["callback"],
                "grant_type": "authorization_code", "code_verifier": attempt["verifier"],
            },
            timeout=10,
        )
        token.raise_for_status()
        profile = requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {token.json()['access_token']}"}, timeout=10,
        )
        profile.raise_for_status()
        identity = profile.json()
        subject = identity["sub"]
        email = identity["email"].strip().lower()
        if not isinstance(subject, str) or not subject or len(subject) > 255 or identity.get("email_verified") is not True:
            raise ValueError
        validate_email(email)
        if len(email) > User._meta.get_field("username").max_length:
            raise ValueError
    except (requests.RequestException, ValidationError, ValueError, KeyError, TypeError, AttributeError):
        messages.error(request, "We could not confirm your Google account. Please try again.")
        return redirect("login")

    user = User.objects.filter(google_subject=subject).first()
    if user is None:
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            messages.error(request, "An account already uses this email. Sign in with your existing password.")
            return redirect("login")
        try:
            with transaction.atomic():
                user = User.objects.create_user(username=email, email=email, google_subject=subject)
        except IntegrityError:
            user = User.objects.filter(google_subject=subject).first()
    if user is None or not user.is_active:
        messages.error(request, "This account cannot sign in with Google.")
        return redirect("login")
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect(attempt.get("next") or "home")
