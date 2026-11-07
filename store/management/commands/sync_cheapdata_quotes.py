import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from store.models import ServicePlan, SupplierQuote


CATALOG_URL = "https://www.cheapdatahub.ng/api/plan-ids/"


class CatalogueRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def normalize_label(label):
    return re.sub(r"[^a-z0-9]", "", label.casefold())


class Command(BaseCommand):
    help = "Refresh CheapDataHub quotes for mapped KoboTap data products without changing retail prices."

    def handle(self, *args, **options):
        try:
            response = requests.get(CATALOG_URL, timeout=20)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError("Could not fetch the CheapDataHub catalogue.") from exc

        parser = CatalogueRows()
        parser.feed(response.text)
        catalogue = {}
        for row in parser.rows:
            if len(row) < 6 or row[1:2] != ["Data"] or row[3] != "bundle_id":
                continue
            network, _, label, _, external_id, price = row[:6]
            try:
                cost = Decimal(price)
                if not external_id.isdecimal() or not cost.is_finite() or not 0 < cost < 100000000:
                    raise ValueError
            except (InvalidOperation, ValueError) as exc:
                raise CommandError("CheapDataHub returned a malformed data quote.") from exc
            if external_id in catalogue:
                raise CommandError("CheapDataHub returned duplicate bundle IDs.")
            catalogue[external_id] = (network, label, cost)
        if not catalogue:
            raise CommandError("No data quotes found. Existing quotes were retained.")

        plans = ServicePlan.objects.filter(
            provider__category__slug__in=("data", "internet-data"),
            provider__vendor__name__iexact="CheapData", vendor_bundle_id__gt=0,
        ).select_related("provider")
        checked_at = timezone.now()
        with transaction.atomic():
            for plan in plans:
                external_id = str(plan.vendor_bundle_id)
                key = {"plan": plan, "vendor_id": plan.provider.vendor_id, "external_id": external_id}
                row = catalogue.get(external_id)
                if row is None:
                    SupplierQuote.objects.filter(**key).update(available=False, checked_at=checked_at)
                    self.stdout.write(f"{plan.code}: missing from supplier catalogue")
                    continue
                network, label, cost = row
                available = "unavailable" not in label.casefold() and network.casefold() == plan.provider.name.casefold()
                quote, _ = SupplierQuote.objects.select_for_update().get_or_create(
                    **key, defaults={"cost": cost, "label": label, "available": available, "checked_at": checked_at},
                )
                label_matches = normalize_label(label) == normalize_label(plan.name)
                quote.approved = available and (label_matches or (
                    quote.approved and normalize_label(label) == normalize_label(quote.label)
                ))
                quote.cost, quote.label, quote.available, quote.checked_at = cost, label, available, checked_at
                quote.save(update_fields=["cost", "label", "available", "checked_at", "approved"])
                self.stdout.write(f"{plan.code}: {cost} NGN; available={available}; approved={quote.approved}")
