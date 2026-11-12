# VTpass public catalogue checked 12 November 2026. No customer purchases made.
from decimal import Decimal, ROUND_CEILING
from django.db import migrations

CATALOGUE = {'dstv': [('dstv3', 'DStv Premium - N44,500', '44500.00'), ('dstv9', 'DStv Premium + French - N69,000', '69000.00'), ('frenchplus-addon', 'DStv French Plus - N24,500', '24500.00'), ('dstv-boxoffice', 'DSTV Box Office - N1,200,000', '1200000.00'), ('dstv-greatwall', 'DStv Great Wall - N3,800', '3800.00'), ('frenchtouch-addon', 'DStv French Touch - N7,000', '7000.00'), ('french11', 'DStv French 11 - N10,800', '10800.00'), ('dstv-movie-bundle-add-on', 'DStv Movie Bundle Add-on E36 - N3500', '3500.00'), ('dstv-hdpvr-access', 'DStv HDPVR Access Service - N6,000', '6000.00'), ('dstv-select36', 'Dstv Select E36 - N11,000', '11000.00'), ('dstv-sports36', 'Dstv Sports E36 - N21,000', '21000.00'), ('dstv-starter36', 'Dstv Starter E36 - N6,000', '6000.00'), ('dstv-premium-streaming', 'DStv Premium Streaming Subscription - 44,500', '44500.00'), ('dstv-sports-ott-streaming', 'DStv Sports Streaming - N21,000', '21000.00'), ('dstv-starter-ott-streaming', 'DStv Starter Streaming - N6,000', '6000.00')], 'gotv': [('gotv-easy', 'Gotv Easy', '4000.00'), ('gotv-starter', 'Gotv Starter', '6000.00'), ('gotv-select', 'Gotv Select', '11000.00'), ('gotv-sports', 'Gotv Sports', '21000.00')], 'startimes': [('nova', 'Nova (Dish) - 2100 Naira - 1 Month', '2100.00'), ('basic', 'Basic (Antenna) - 4,000 Naira - 1 Month', '4000.00'), ('smart', 'Basic (Dish) - 5,100 Naira - 1 Month', '5100.00'), ('classic', 'Classic (Antenna) - 6000 Naira - 1 Month', '6000.00'), ('super', 'Super (Dish) - 9,800 Naira - 1 Month', '9800.00'), ('nova-weekly', 'Nova (Antenna) - 700 Naira - 1 Week', '700.00'), ('basic-weekly', 'Basic (Antenna) - 1400 Naira - 1 Week', '1400.00'), ('smart-weekly', 'Basic (Dish) - 1,700 Naira - 1 Week', '1700.00'), ('classic-weekly', 'Classic (Antenna) - 2000 Naira - 1 Week', '2000.00'), ('super-weekly', 'Super (Dish) - 3,300 Naira - 1 Week', '3300.00'), ('uni-1', 'Chinese (Dish) - 21,000 Naira - 1 month', '21000.00'), ('uni-2', 'Nova (Antenna) - 2,100 Naira - 1 Month', '2100.00'), ('special-weekly', 'Classic (Dish) - 2300 Naira - 1 Week', '2300.00'), ('special-monthly', 'Classic (Dish) - 7400 Naira - 1 Month', '7400.00'), ('nova-dish-weekly', 'Nova (Dish) - 700 Naira - 1 Week', '700.00'), ('super-antenna-weekly', 'Super (Antenna) - 3,200 Naira - 1 Week', '3200.00'), ('super-antenna-monthly', 'Super (Antenna) - 9,500 Naira - 1 Month', '9500.00'), ('classic-weekly-dish', 'Classic (Dish) - 2500 Naira - 1 Week', '2500.00'), ('global-monthly-dish', 'Global (Dish) - 21000 Naira - 1 Month', '21000.00'), ('global-weekly-dish', 'Global (Dish) - 7000 Naira - 1Week', '7000.00'), ('shs-weekly-2800', 'Startimes SHS - 2,800 Naira - Weekly', '2800.00'), ('shs-weekly-4620', 'Startimes SHS - 4,620 Naira - Weekly', '4620.00'), ('shs-weekly-4900', 'Startimes SHS - 4,900 Naira - Weekly', '4900.00'), ('shs-weekly-9100', 'Startimes SHS - 9,100 Naira - Weekly', '9100.00'), ('shs-monthly-12000', 'Startimes SHS - 12,000 Naira - Monthly', '12000.00'), ('shs-monthly-19800', 'Startimes SHS - 19,800 Naira - Monthly', '19800.00'), ('shs-monthly-21000', 'Startimes SHS - 21,000 Naira - Monthly', '21000.00'), ('shs-monthly-39000', 'Startimes SHS - 39,000 Naira - Monthly', '39000.00')]}


def refresh_tv(apps, schema_editor):
    alias = schema_editor.connection.alias
    Category = apps.get_model("store", "ServiceCategory")
    Provider = apps.get_model("store", "ServiceProvider")
    Plan = apps.get_model("store", "ServicePlan")
    category, _ = Category.objects.using(alias).get_or_create(slug="cable-tv", defaults={"name": "Cable TV"})
    rates = {"dstv": Decimal("0.015"), "gotv": Decimal("0.015"), "startimes": Decimal("0.02")}
    names = {"dstv": "DStv", "gotv": "GOtv", "startimes": "StarTimes"}
    for service, rows in CATALOGUE.items():
        provider = Provider.objects.using(alias).filter(category=category, vtpass_service_id=service).first()
        if provider is None:
            provider = Provider.objects.using(alias).filter(category=category, name__iexact=names[service]).first()
        if provider is None:
            provider = Provider(category=category)
        provider.name = names[service]
        provider.vtpass_service_id = service
        provider.is_active = True
        provider.save(using=alias)
        # Old packages remain in transaction history, but cannot be purchased.
        Plan.objects.using(alias).filter(provider=provider).update(is_active=False)
        for code, name, raw_price in rows:
            face = Decimal(raw_price)
            cost = (face * (1 - rates[service])).quantize(Decimal("0.01"))
            # Cover the existing 5.5% wallet funding reserve and target N30
            # contribution after supplier cost; hosting/tax remain separate.
            total = ((cost + 30) / Decimal("0.945") / 10).to_integral_value(rounding=ROUND_CEILING) * 10
            plan = Plan.objects.using(alias).filter(provider=provider, vtpass_variation_code=code).first()
            if plan is None:
                plan, _ = Plan.objects.using(alias).get_or_create(code="VTP-TV-" + service + "-" + code, defaults={"provider": provider, "name": name[:100]})
            plan.name = name[:100]
            plan.vtpass_variation_code = code
            plan.cost_price = cost
            plan.market_price = face
            plan.selling_price = total
            plan.is_active = True
            plan.save(using=alias)


class Migration(migrations.Migration):
    dependencies = [("store", "0022_cable_price_breakdown")]
    operations = [migrations.RunPython(refresh_tv, migrations.RunPython.noop)]
