from django.db import migrations


def expand_beta_data_catalogue(apps, schema_editor):
    alias = schema_editor.connection.alias
    plans = apps.get_model("store", "ServicePlan").objects.using(alias)
    providers = apps.get_model("store", "ServiceProvider").objects.using(alias).filter(
        category__slug="internet-data",
        vendor__name__iexact="CheapData",
        is_active=True,
    )

    for network, bundle_id, name, cost, price in (
        ("GLO", 42, "200MB Corporate Gifting (1 Day)", 92, 135),
        ("GLO", 84, "1GB Awoof (1 Day)", 250, 310),
        ("GLO", 37, "3GB Corporate Gifting (30 Days)", 1300, 1480),
        ("MTN", 44, "500MB Data Share (30 Days)", 300, 365),
        ("MTN", 49, "3GB SME (30 Days)", 1370, 1550),
        ("AIRTEL", 69, "1.5GB Gifting (1 Day)", 500, 590),
    ):
        provider = providers.filter(name__iexact=network).first()
        if provider is None or plans.filter(provider=provider, vendor_bundle_id=bundle_id).exists():
            continue
        plans.get_or_create(
            code=f"CDH-DATA-{bundle_id}",
            defaults={
                "provider": provider,
                "name": name,
                "vendor_bundle_id": bundle_id,
                "cost_price": cost,
                "selling_price": price,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("store", "0017_update_airtel_beta_offers")]

    operations = [migrations.RunPython(expand_beta_data_catalogue, migrations.RunPython.noop)]
