"""Transactional phone verification; no codes or provider responses are logged."""
from urllib.parse import urlparse
from datetime import timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .authentication import normalize_phone


def sms_otp_enabled():
    return bool(settings.SMS_OTP_ENABLED and settings.TERMII_API_KEY and
                settings.TERMII_SENDER_ID and settings.TERMII_BASE_URL)


def send_sms_otp(phone, code):
    phone = normalize_phone(phone)
    base = settings.TERMII_BASE_URL.rstrip('/')
    parsed = urlparse(base)
    if (not sms_otp_enabled() or not phone or parsed.scheme != 'https' or
            not parsed.hostname or not parsed.hostname.endswith('.termii.com') or
            parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise OSError('SMS verification is not configured')
    from .models import SmsOtpLimit
    # Shared database limits survive restarts and cover all web workers/sessions.
    now = timezone.now()
    key = salted_hmac('sms-otp-limit', phone).hexdigest()
    with transaction.atomic():
        SmsOtpLimit.objects.get_or_create(key='global', defaults={'window_started_at': now})
        budget = SmsOtpLimit.objects.select_for_update().get(key='global')
        if now - budget.window_started_at >= timedelta(hours=1):
            budget.attempts = 0
            budget.window_started_at = now
        if budget.attempts >= settings.SMS_OTP_HOURLY_LIMIT:
            raise OSError('SMS temporarily paused; use email verification')
        SmsOtpLimit.objects.get_or_create(key=key, defaults={'window_started_at': now})
        limit = SmsOtpLimit.objects.select_for_update().get(key=key)
        if now - limit.window_started_at >= timedelta(hours=1):
            limit.attempts = 0
            limit.window_started_at = now
        if limit.attempts >= 3:
            raise OSError('Please use email verification or try SMS later')
        limit.attempts += 1
        limit.save(update_fields=['window_started_at', 'attempts'])
        budget.attempts += 1
        budget.save(update_fields=['window_started_at', 'attempts'])
    try:
        response = requests.post(
            base + '/api/sms/send',
            json={
                'api_key': settings.TERMII_API_KEY,
                'to': '234' + phone[1:],
                'from': settings.TERMII_SENDER_ID,
                'sms': f'Your Payvict verification code is {code}. Valid for 10 minutes. Do not share this code.',
                'type': 'plain', 'channel': 'dnd',
            }, timeout=10,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or not result.get('message_id'):
            raise OSError('SMS provider did not accept the message')
    except (requests.RequestException, ValueError) as exc:
        raise OSError('SMS verification is temporarily unavailable') from None
