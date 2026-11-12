import time

from django.conf import settings
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.cache import add_never_cache_headers


class IdleSessionMiddleware:
    """Enforce inactivity on the server; background preloads cannot extend it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        now = int(time.time())
        authenticated = request.user.is_authenticated
        exempt = request.path == "/paystack_webhook/"
        if authenticated and not exempt:
            last = request.session.get("payvict_last_activity", now)
            if now - last >= settings.SESSION_IDLE_TIMEOUT:
                logout(request)
                if request.path != reverse("login"):
                    target = reverse("login") + "?expired=1"
                    response = JsonResponse({"authenticated": False, "redirect": target}, status=401) if "application/json" in request.headers.get("Accept", "") else redirect(target)
                    add_never_cache_headers(response)
                    return response
            elif not (request.path in (reverse("login"), "/health/") or request.headers.get("X-Payvict-Prefetch") == "1"):
                request.session["payvict_last_activity"] = now
                request.session.set_expiry(settings.SESSION_IDLE_TIMEOUT)
        response = self.get_response(request)
        if request.user.is_authenticated and not authenticated:
            request.session["payvict_last_activity"] = now
            request.session.set_expiry(settings.SESSION_IDLE_TIMEOUT)
        return response
