from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from django.apps import apps
from django.test import SimpleTestCase, TestCase
from store.models import ServicePlan, Vendor
from store.supplier_pricing import estimated_data_margin


class MtnCompetitivePriceTests(SimpleTestCase):
    def test_revised_prices_include_cashback_and_keep_expense_reserves(self):
        for cost, price in [('250', '310'), ('450', '795'), ('1150', '1495')]:
            with self.subTest(cost=cost):
                plan = ServicePlan(cost_price=Decimal(cost), selling_price=Decimal(price))
                self.assertGreater(plan.reward_amount, 0)
                self.assertGreaterEqual(estimated_data_margin(plan, Decimal(cost)), Decimal('30'))

    def test_undercutting_supplier_face_price_is_a_loss(self):
        plan = ServicePlan(cost_price=Decimal('900'), selling_price=Decimal('895'))
        self.assertLess(estimated_data_margin(plan, Decimal('900')), 0)


class MtnPriceMigrationTests(TestCase):
    def setUp(self):
        Vendor.objects.create(name='CheapData', is_active=True)
        self.editor = SimpleNamespace(connection=SimpleNamespace(alias='default'))
        import_module('store.migrations.0025_expand_available_data_catalogue').expand_data(apps, self.editor)
        for bundle, old_price in [(76, '340'), (45, '799'), (48, '1498')]:
            ServicePlan.objects.filter(provider__name__iexact='MTN', vendor_bundle_id=bundle).update(selling_price=old_price)
        self.correct = import_module('store.migrations.0027_correct_mtn_competitive_prices').correct_prices
        self.correct(apps, self.editor)

    def test_catalogue_migration_applies_safe_corrections(self):
        for bundle, price in [(76, '310'), (45, '795'), (48, '1495')]:
            with self.subTest(bundle=bundle):
                plan = ServicePlan.objects.get(provider__name__iexact='MTN',
                    provider__vendor__name__iexact='CheapData', vendor_bundle_id=bundle)
                self.assertEqual(plan.selling_price, Decimal(price))
                self.assertGreaterEqual(estimated_data_margin(plan, plan.cost_price), Decimal('30'))

    def test_changed_cost_or_already_lower_price_is_not_overwritten(self):
        plan = ServicePlan.objects.get(provider__name__iexact='MTN', vendor_bundle_id=45)
        plan.selling_price = Decimal('900')
        plan.cost_price = Decimal('600')
        plan.save()
        self.correct(apps, self.editor)
        plan.refresh_from_db()
        self.assertEqual(plan.selling_price, Decimal('900'))
        plan.cost_price = Decimal('450')
        plan.selling_price = Decimal('790')
        plan.save()
        self.correct(apps, self.editor)
        plan.refresh_from_db()
        self.assertEqual(plan.selling_price, Decimal('790'))
