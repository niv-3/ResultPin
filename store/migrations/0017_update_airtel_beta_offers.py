from django.db import migrations


def update_airtel_beta_offers(apps, schema_editor):
    alias = schema_editor.connection.alias
    plans = apps.get_model("store", "ServicePlan").objects.using(alias)
    provider = apps.get_model("store", "ServiceProvider").objects.using(alias).filter(
        name__iexact="Airtel",
        category__slug="internet-data",
        vendor__name__iexact="CheapData",
    ).first()
    if provider is None:
        return

    airtel = plans.filter(provider=provider)
    airtel.filter(vendor_bundle_id=52, selling_price=1725).update(
        cost_price=1570, selling_price=1772, market_price=None
    )
    # The comparable OPay offers leave no room for our cost and fee allowances.
    airtel.filter(vendor_bundle_id=13, selling_price=575).update(is_active=False)
    airtel.filter(vendor_bundle_id=66, selling_price=700).update(is_active=False)

    if not airtel.filter(vendor_bundle_id=70).exists():
        plans.get_or_create(
            code="CDH-DATA-70",
            defaults={
                "provider": provider,
                "name": "1GB Social Bundle (3 Days)",
                "vendor_bundle_id": 70,
                "cost_price": 295,
                "selling_price": 360,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("store", "0016_activate_simulated_beta_bundles")]

    operations = [migrations.RunPython(update_airtel_beta_offers, migrations.RunPython.noop)]
