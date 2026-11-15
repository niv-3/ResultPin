from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command
from django.db import transaction
from django.utils import timezone

from store.models import SupplierQuote


class Command(BaseCommand):
    help = "Refresh mapped supplier costs. Never changes retail prices or approves new mappings."

    def add_arguments(self, parser):
        parser.add_argument("--supplier", choices=("cheapdata", "nellobyte"), required=True)

    def handle(self, *args, **options):
        if options["supplier"] == "cheapdata":
            return call_command("sync_cheapdata_quotes", stdout=self.stdout)
        if not settings.NELLOBYTE_USER_ID:
            raise CommandError("Set NELLOBYTE_USER_ID privately before refreshing account prices.")
        try:
            response = requests.get(
                "https://www.nellobytesystems.com/APIDatabundlePlansV3.asp",
                params={"UserID": settings.NELLOBYTE_USER_ID}, timeout=25, allow_redirects=False,
            )
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError
            networks = response.json()["MOBILE_NETWORK"]
            catalogue = {}
            for network, groups in networks.items():
                for group in groups:
                    for item in group["PRODUCT"]:
                        cost = Decimal(str(item["PRODUCT_AMOUNT"]))
                        if not cost.is_finite() or cost <= 0:
                            raise ValueError
                        key = (str(group["ID"]), str(item["PRODUCT_CODE"]))
                        if key in catalogue:
                            raise ValueError
                        catalogue[key] = (network, str(item["PRODUCT_NAME"]), cost)
            if not catalogue:
                raise ValueError
        except (requests.RequestException, ValueError, KeyError, TypeError, InvalidOperation):
            # Do not attach exception text containing URLs or account identifiers.
            raise CommandError("Could not validate Nellobyte's catalogue; existing quotes retained.") from None
        count = 0
        with transaction.atomic():
            quotes = SupplierQuote.objects.select_for_update().select_related("plan__provider").filter(
                vendor__data_supplier__adapter="nellobyte")
            for quote in quotes:
                item = catalogue.get((quote.network_code, quote.external_id))
                if item is None:
                    quote.available = False
                else:
                    network, label, cost = item
                    network_matches = network.casefold() == quote.plan.provider.name.casefold()
                    # Plan type, expiry and bonuses must first be manually checked and approved.
                    quote.approved = quote.approved and network_matches and quote.label == label
                    quote.cost, quote.label, quote.available = cost, label, network_matches
                quote.checked_at = timezone.now()
                quote.save(update_fields=["cost", "label", "available", "approved", "checked_at"])
                count += 1
        self.stdout.write(self.style.SUCCESS(f"Refreshed {count} mapped quotes; retail prices unchanged."))
