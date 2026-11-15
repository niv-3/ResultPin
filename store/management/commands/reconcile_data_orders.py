from datetime import timedelta

import requests
from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from store.data_routing import credentials_ready
from store.models import AirtimeTransaction, WalletTransaction


class Command(BaseCommand):
    help = "Query uncertain Nellobyte orders; settle confirmed successes once. Never repeats a purchase."

    def handle(self, *args, **options):
        if not credentials_ready("nellobyte"):
            raise CommandError("Nellobyte credentials are not configured.")
        orders = AirtimeTransaction.objects.filter(
            supplier_adapter="nellobyte", created_at__lte=timezone.now() - timedelta(minutes=2),
        ).filter(status="processing") | AirtimeTransaction.objects.filter(
            supplier_adapter="nellobyte", payment_method="wallet", status="pending",
            created_at__lte=timezone.now() - timedelta(minutes=2),
        )
        settled = 0
        for order in orders:
            try:
                response = requests.get("https://www.nellobytesystems.com/APIQueryV1.asp",
                    params={"UserID": settings.NELLOBYTE_USER_ID, "APIKey": settings.NELLOBYTE_API_KEY,
                            "RequestID": order.reference}, timeout=25, allow_redirects=False)
                if response.status_code != 200:
                    continue
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("status") != "ORDER_COMPLETED":
                    continue
            except (requests.RequestException, ValueError):
                continue
            with transaction.atomic():
                locked = AirtimeTransaction.objects.select_for_update().get(pk=order.pk)
                if locked.status not in ("pending", "processing"):
                    continue
                # The authenticated query is for our unique request, never a caller-supplied webhook.
                locked.status = "success"
                locked.supplier_reference = str(payload.get("orderid", ""))[:100]
                locked.save(update_fields=["status", "supplier_reference"])
                reward = locked.cashback_snapshot or 0
                if reward and locked.user_id and not WalletTransaction.objects.filter(reference=f"REWARD-{locked.reference}").exists():
                    locked.user.credit_wallet(reward, source="cashback_reward",
                        reference=f"REWARD-{locked.reference}", description="Cashback reward for data purchase")
                settled += 1
        self.stdout.write(f"Confirmed {settled} successful orders. Unconfirmed orders retained for review.")
