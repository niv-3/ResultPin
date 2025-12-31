import requests
from django.conf import settings


PAYSTACK_BASE_URL = "https://api.paystack.co"


def initialize_paystack(email, amount, reference, callback_url):
    """
    Initialize Paystack transaction
    Amount must be in kobo
    """
    url = f"{PAYSTACK_BASE_URL}/transaction/initialize"

    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "email": email,
        "amount": int(amount),  # already converted to kobo
        "reference": reference,
        "callback_url": callback_url,
    }

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    return response.json()


def verify_paystack(reference):
    """
    Verify Paystack transaction
    """
    url = f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}"

    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
    }

    response = requests.get(url, headers=headers, timeout=30)
    return response.json()
