from django.db import migrations


def activate_simulated_beta_bundles(apps, schema_editor):
    plans = apps.get_model("store", "ServicePlan").objects.using(
        schema_editor.connection.alias
    )
    for network, bundle_id in (("MTN", 48), ("GLO", 54), ("AIRTEL", 13), ("AIRTEL", 66)):
        plans.filter(
            code=f"CDH-DATA-{bundle_id}",
            vendor_bundle_id=bundle_id,
            provider__name__iexact=network,
            provider__category__slug="internet-data",
            provider__vendor__name__iexact="CheapData",
            selling_price__gt=0,
        ).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [("store", "0015_stage_airtel_data_plans")]

    operations = [migrations.RunPython(activate_simulated_beta_bundles, migrations.RunPython.noop)]
