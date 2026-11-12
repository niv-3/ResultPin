from django.db import migrations


def pause_airtime(apps, schema_editor):
    apps.get_model("store", "ServiceCategory").objects.using(
        schema_editor.connection.alias
    ).filter(slug="airtime").update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("store", "0020_airtimetransaction_supplier_reference")]
    operations = [migrations.RunPython(pause_airtime, migrations.RunPython.noop)]
