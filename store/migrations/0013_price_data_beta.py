from decimal import Decimal

from django.db import migrations


def price_data_beta(apps, schema_editor):
    alias = schema_editor.connection.alias
    plans = apps.get_model("store", "ServicePlan").objects.using(alias)
    providers = apps.get_model("store", "ServiceProvider").objects.using(alias)
    data_providers = providers.filter(
        category__slug="internet-data", vendor__name__iexact="CheapData"
    )

    # Benchmarks use OPay's displayed price less cashback from the supplied screenshots.
    for bundle_id, old_price, new_price, market_price in (
        (68, 355, 388, 400),  # Glo 1GB, 3 days
        (45, 550, 794, 800),  # MTN 1GB, 7 days
        (76, 305, 340, 350),  # MTN 500MB, Payvict validity is one day longer
    ):
        plans.filter(
            provider__in=data_providers,
            vendor_bundle_id=bundle_id,
            selling_price=Decimal(old_price),
        ).update(selling_price=Decimal(new_price), market_price=Decimal(market_price))

    # Stage new plans for delivery verification before offering them to buyers.
    for network, bundle_id, name, cost, price, market in (
        ("MTN", 48, "2GB SME (30 Days)", 1150, 1498, 1500),
        ("GLO", 54, "5GB Corporate Gifting (7 Days)", 1699, 2019, 2020),
    ):
        provider = data_providers.filter(name__iexact=network).first()
        if provider is None or plans.filter(provider=provider, vendor_bundle_id=bundle_id).exists():
            continue
        plans.get_or_create(
            code=f"CDH-DATA-{bundle_id}",
            defaults={
                "provider": provider,
                "name": name,
                "vendor_bundle_id": bundle_id,
                "cost_price": Decimal(cost),
                "selling_price": Decimal(price),
                "market_price": Decimal(market),
                "is_active": False,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("store", "0012_correct_mtn_airtime_price")]

    operations = [migrations.RunPython(price_data_beta, migrations.RunPython.noop)]
