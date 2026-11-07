from django.db import migrations


def stage_airtel_data_plans(apps, schema_editor):
    alias = schema_editor.connection.alias
    providers = apps.get_model("store", "ServiceProvider").objects.using(alias)
    plans = apps.get_model("store", "ServicePlan").objects.using(alias)
    provider = providers.filter(
        name__iexact="Airtel",
        category__slug="internet-data",
        vendor__name__iexact="CheapData",
    ).first()
    if provider is None:
        return

    for bundle_id, name, cost, price in (
        (13, "500MB Gifting (7 days)", 490, 575),
        (66, "1.5GB Gifting (2 Days)", 599, 700),
    ):
        if plans.filter(provider=provider, vendor_bundle_id=bundle_id).exists():
            continue
        plans.get_or_create(
            code=f"CDH-DATA-{bundle_id}",
            defaults={
                "provider": provider,
                "name": name,
                "vendor_bundle_id": bundle_id,
                "cost_price": cost,
                "selling_price": price,
                "is_active": False,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("store", "0014_adjust_beta_data_prices")]

    operations = [migrations.RunPython(stage_airtel_data_plans, migrations.RunPython.noop)]
