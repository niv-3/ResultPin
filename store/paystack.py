import requests
from django.conf import settings


def initialize_paystack(email, amount, reference, callback_url):
    response = requests.post(
        "https://api.paystack.co/transaction/initialize",
        json={
            "email": email,
            "amount": int(amount),
            "reference": reference,
            "callback_url": callback_url,
        },
        headers={
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    return response.json()


def verify_paystack(reference):
    """
    READ-ONLY verification
    NEVER credit wallet here
    """
    response = requests.get(
        f"https://api.paystack.co/transaction/verify/{reference}",
        headers={
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        },
        timeout=30,
    )

    return response.json()
