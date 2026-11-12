# CheapDataHub public catalogue checked 12 November 2026; no live purchases.
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from django.db import migrations
from django.utils import timezone

CATALOGUE = [('AIRTEL', 70, '1GB (Social Bundle) Gifting (3 Days)', '295.0'), ('AIRTEL', 13, '500MB Gifting (7 days)', '490.0'), ('AIRTEL', 69, '1.5GB Gifting (1 Day)', '500.0'), ('AIRTEL', 66, '1.5GB Gifting (2 Days)', '599.0'), ('AIRTEL', 15, '1GB Gifting (7 Days)', '800.0'), ('AIRTEL', 17, '2GB Gifting (30 Days)', '1490.0'), ('AIRTEL', 52, '5GB Gifting (7 Days)', '1570.0'), ('AIRTEL', 18, '3GB Gifting (30 Days)', '1960.0'), ('AIRTEL', 22, '6GB SME (7 Days)', '2455.0'), ('AIRTEL', 19, '4GB Gifting (30 Days)', '2570.0'), ('AIRTEL', 20, '8GB Gifting (30 Days)', '2999.0'), ('AIRTEL', 21, '10GB Gifting (30 Days)', '4070.0'), ('GLO', 42, '200 MB corprate gifting (1 Day)', '92.0'), ('GLO', 35, '500MB corprate gifting (30 Days)', '225.0'), ('GLO', 84, '1GB Awoof (1 Day)', '250.0'), ('GLO', 68, '1GB corprate gifting (3 Days)', '300.0'), ('GLO', 36, '1GB corprate gifting (30 Days)', '425.0'), ('GLO', 41, '1GB Gifting (14 Days)', '485.0'), ('GLO', 40, '2GB corprate gifting (30 Days)', '850.0'), ('GLO', 37, '3GB corprate gifting (30 Days)', '1300.0'), ('GLO', 54, '5GB corprate gifting (7 Days)', '1699.0'), ('GLO', 38, '5GB corprate gifting (30 Days)', '2250.0'), ('GLO', 39, '10GB corprate gifting (30 Days)', '4390.0'), ('GLO', 59, '20.5GB Gifting (30 Days)', '5300.0'), ('GLO', 58, '107GB Gifting (30 Days)', '19300.0'), ('MTN', 43, '110MB Gifting (1 Day)', '99.0'), ('MTN', 74, '230MB Gifting (1 Day)', '200.0'), ('MTN', 76, '500MB SME (2 Days)', '250.0'), ('MTN', 44, '500MB data share (30 Days)', '300.0'), ('MTN', 77, '1GB SME (2 Days)', '399.0'), ('MTN', 81, '(UNAVAILABLE) 1 GB Awoof (30 Days)', '400.0'), ('MTN', 78, '1GB Awoof (30 Days)', '430.0'), ('MTN', 45, '1GB SME (7 Days)', '450.0'), ('MTN', 46, '1GB SME (30 Days)', '570.0'), ('MTN', 83, '(Unavailable) 3GB Awoof (30 Days)', '750.0'), ('MTN', 71, '2GB Gifting (7 Days)', '900.0'), ('MTN', 27, '2.5GB Gifting (2 Days)', '900.0'), ('MTN', 47, '2GB SME (7 Days)', '930.0'), ('MTN', 60, '3.5GB Gifting (1 Day)', '1050.0'), ('MTN', 48, '2GB SME (30 Days)', '1150.0'), ('MTN', 61, '4GB Gifting (2 Days)', '1175.0'), ('MTN', 49, '3GB SME (30 Days)', '1370.0'), ('MTN', 50, '5GB SME (30 Days)', '2050.0'), ('MTN', 53, '6GB Gifting (7 Days)', '2495.0'), ('MTN', 55, '11GB Gifting (7 Days)', '3550.0'), ('MTN', 33, '7GB Gifting (30 Days)', '3600.0'), ('MTN', 67, '10GB Gifting (30 Days)', '4800.0'), ('MTN', 57, '36GB Gifting (30 Days)', '10900.0'), ('MTN', 51, '75GB SME (30 Days)', '17990.0')]


def minimum_price(cost):
    funded_cost = cost * Decimal("1.03")
    uncapped = (funded_cost + 30) / Decimal("0.93")
    capped = (funded_cost + 60) / Decimal("0.945")
    price = (min(uncapped, capped) / 5).to_integral_value(rounding=ROUND_CEILING) * 5
    while True:
        reward = min((price * Decimal("0.015")).quantize(Decimal("0.01")), Decimal("30"))
        funding = (price * Decimal("0.055")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        supplier_funding = (cost * Decimal("0.03")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if price - cost - reward - funding - supplier_funding >= 30:
            return price
        price += 5


def expand_data(apps, schema_editor):
    alias = schema_editor.connection.alias
    Vendor = apps.get_model("store", "Vendor")
    Category = apps.get_model("store", "ServiceCategory")
    Provider = apps.get_model("store", "ServiceProvider")
    Plan = apps.get_model("store", "ServicePlan")
    Quote = apps.get_model("store", "SupplierQuote")
    vendor = Vendor.objects.using(alias).filter(name__iexact="CheapData", is_active=True).first()
    if vendor is None:
        return
    category, _ = Category.objects.using(alias).get_or_create(slug="internet-data", defaults={"name": "Data", "is_active": True})
    providers = {}
    for network in ("MTN", "GLO", "AIRTEL"):
        provider = Provider.objects.using(alias).filter(category=category, name__iexact=network, vendor=vendor).first()
        if provider is None:
            provider = Provider.objects.using(alias).create(category=category, name=network, vendor=vendor, is_active=True)
        providers[network] = provider
    checked_at = timezone.now()
    available_ids = []
    for network, bundle_id, label, raw_cost in CATALOGUE:
        provider = providers[network]
        cost = Decimal(raw_cost)
        available = "unavailable" not in label.casefold()
        if not available:
            Plan.objects.using(alias).filter(provider=provider, vendor_bundle_id=bundle_id).update(is_active=False)
            Quote.objects.using(alias).filter(plan__provider=provider, external_id=str(bundle_id)).update(available=False, checked_at=checked_at)
            continue
        available_ids.append(bundle_id)
        plan = Plan.objects.using(alias).filter(provider=provider, vendor_bundle_id=bundle_id).first()
        if plan is None:
            plan = Plan(provider=provider, vendor_bundle_id=bundle_id, code="CDH-DATA-" + str(bundle_id))
        floor = minimum_price(cost)
        # Keep existing customer prices where they still meet the margin floor.
        plan.selling_price = max(plan.selling_price or 0, floor)
        plan.cost_price = cost
        plan.name = label.replace("corprate gifting", "Corporate Gifting").replace("data share", "Data Share")
        plan.is_active = True
        plan.save(using=alias)
        Quote.objects.using(alias).update_or_create(plan=plan, vendor=vendor, external_id=str(bundle_id), defaults={
            "label": label, "cost": cost, "available": True, "approved": True, "checked_at": checked_at,
        })
    # Removed supplier IDs cannot remain buyable through old checkout links.
    obsolete = Plan.objects.using(alias).filter(provider__in=providers.values()).exclude(vendor_bundle_id__in=available_ids)
    Quote.objects.using(alias).filter(plan__in=obsolete).update(available=False, checked_at=checked_at)
    obsolete.update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("store", "0024_publish_service_guides")]
    operations = [migrations.RunPython(expand_data, migrations.RunPython.noop)]
