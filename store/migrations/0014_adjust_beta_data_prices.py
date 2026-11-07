from django.db import migrations


def adjust_beta_data_prices(apps, schema_editor):
    plans = apps.get_model("store", "ServicePlan").objects.using(
        schema_editor.connection.alias
    ).filter(
        provider__category__slug="internet-data",
        provider__vendor__name__iexact="CheapData",
    )
    plans.filter(vendor_bundle_id=68, selling_price=388).update(selling_price=393)
    plans.filter(vendor_bundle_id=45, selling_price=794).update(selling_price=799)


class Migration(migrations.Migration):
    dependencies = [("store", "0013_price_data_beta")]

    operations = [migrations.RunPython(adjust_beta_data_prices, migrations.RunPython.noop)]
