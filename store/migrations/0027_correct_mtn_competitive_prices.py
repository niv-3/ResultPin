from decimal import Decimal

from django.db import migrations


# Supplier costs checked against CheapDataHub's public API catalogue 14 Nov 2026.
# OPay size/validity benchmarks are from the customer's 7 Nov screenshots,
# not a live OPay feed. Do not reprice unmatched bundles as equivalent products.
PRICES = {
    76: ('250.00', '310.00'),  # 500MB SME, 2 days: lowest rounded safe price.
    45: ('450.00', '795.00'),  # 1GB SME, 7 days: N5 below the N800 benchmark.
    48: ('1150.00', '1495.00'),  # 2GB SME, 30 days: N5 below N1500 benchmark.
}


def correct_prices(apps, schema_editor):
    Plan = apps.get_model('store', 'ServicePlan')
    for bundle_id, (expected_cost, price) in PRICES.items():
        Plan.objects.using(schema_editor.connection.alias).filter(
            provider__name__iexact='MTN',
            provider__category__slug__in=['data', 'internet-data'],
            provider__vendor__name__iexact='CheapData',
            vendor_bundle_id=bundle_id,
            cost_price=Decimal(expected_cost),
            selling_price__gt=Decimal(price),
        ).update(selling_price=Decimal(price))


class Migration(migrations.Migration):
    dependencies = [('store', '0026_smsotplimit')]
    operations = [migrations.RunPython(correct_prices, migrations.RunPython.noop)]
