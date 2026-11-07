from decimal import Decimal

from django.db import migrations


def correct_mtn_airtime_price(apps, schema_editor):
    service_plan = apps.get_model("store", "ServicePlan")
    plans = service_plan.objects.using(schema_editor.connection.alias).filter(
        code="MTN-100",
        provider__category__slug="airtime",
        cost_price=Decimal("95.00"),
    )
    plans.filter(selling_price=Decimal("100.00")).update(selling_price=Decimal("110.00"))
    plans.update(cost_price=Decimal("100.00"))


class Migration(migrations.Migration):
    dependencies = [("store", "0011_user_google_subject")]

    operations = [
        migrations.RunPython(correct_mtn_airtime_price, migrations.RunPython.noop),
    ]
