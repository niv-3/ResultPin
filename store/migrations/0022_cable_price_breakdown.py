from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("store", "0021_pause_airtime")]
    operations = [
        migrations.AddField(model_name="cabletransaction", name="package_amount", field=models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)),
        migrations.AddField(model_name="cabletransaction", name="service_fee", field=models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)),
    ]
