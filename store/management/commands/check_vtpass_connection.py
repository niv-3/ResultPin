import requests

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Check VTpass authentication without submitting a purchase or printing credentials."

    def handle(self, *args, **options):
        if settings.VTPASS_TEST_MODE:
            self.stdout.write("VTPASS CHECK: sandbox mode; live check skipped.")
            return
        if not all((settings.VTPASS_API_KEY, settings.VTPASS_PUBLIC_KEY, settings.VTPASS_SECRET_KEY)):
            self.stdout.write("VTPASS CHECK: incomplete credentials.")
            return
        try:
            response = requests.get(
                "https://vtpass.com/api/balance",
                headers={"api-key": settings.VTPASS_API_KEY, "public-key": settings.VTPASS_PUBLIC_KEY},
                timeout=15,
            )
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError):
            self.stdout.write("VTPASS CHECK: connection failed.")
            return
        if not isinstance(result, dict):
            self.stdout.write("VTPASS CHECK: unexpected response.")
            return
        content = result.get("contents")
        if str(result.get("code")) == "1" and isinstance(content, dict) and "balance" in content:
            self.stdout.write("VTPASS CHECK: live authentication successful.")
        else:
            code = str(result.get("code", "missing"))
            self.stdout.write(f"VTPASS CHECK: authentication not confirmed (code {code[:10]}).")
