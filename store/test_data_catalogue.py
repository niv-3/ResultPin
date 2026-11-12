import importlib
import json
from collections import Counter
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.apps import apps
from django.test import TestCase, override_settings

from store.models import AirtimeTransaction, ServiceCategory, ServicePlan, SupplierQuote, User, Vendor
from store.supplier_pricing import estimated_data_margin


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["testserver"], DATA_QUOTE_GUARD_ENABLED=True)
class ExpandedDataCatalogueTests(TestCase):
    def setUp(self):
        Vendor.objects.create(name="CheapData", is_active=True)
        migration = importlib.import_module("store.migrations.0025_expand_available_data_catalogue")
        migration.expand_data(apps, SimpleNamespace(connection=SimpleNamespace(alias="default")))
        self.plans = ServicePlan.objects.filter(provider__category__slug="internet-data", is_active=True).select_related("provider")
        self.user = User.objects.create_user(username="data-check", email="data-check@example.com")
        self.user.credit_wallet(2000000)
        self.client.force_login(self.user)

    def buy(self, plan):
        return self.client.post(f"/service/pay/internet-data/{plan.pk}/", data=json.dumps({
            "phone": "08012345678", "payment_method": "wallet", "expected_price": str(plan.selling_price),
        }), content_type="application/json")

    def test_all_available_network_bundles_have_margin_cashback_and_approved_mappings(self):
        self.assertEqual(Counter(self.plans.values_list("provider__name", flat=True)), {"MTN": 22, "GLO": 13, "AIRTEL": 12})
        for plan in self.plans:
            with self.subTest(plan=plan.code):
                self.assertGreater(plan.reward_amount, 0)
                self.assertGreaterEqual(estimated_data_margin(plan, plan.cost_price), 30)
                self.assertGreaterEqual(estimated_data_margin(plan, plan.cost_price, "card"), 30)
                self.assertTrue(SupplierQuote.objects.filter(plan=plan, external_id=str(plan.vendor_bundle_id), approved=True, available=True, cost=plan.cost_price).exists())
        self.assertFalse(self.plans.filter(vendor_bundle_id__in=[81, 83]).exists())
        self.assertFalse(ServiceCategory.objects.filter(slug="airtime", is_active=True).exists())

    def test_every_bundle_simulates_wallet_checkout_and_correct_supplier_id(self):
        response = Mock(headers={"Content-Type": "application/json"})
        response.json.return_value = {"status": "success"}
        for plan in self.plans:
            with self.subTest(plan=plan.code), patch("store.views.requests.post", return_value=response) as supplier:
                before = self.user.wallet_balance
                result = self.buy(plan)
                self.assertTrue(result.json()["status"], result.content)
                self.assertEqual(supplier.call_args.kwargs["json"], {"bundle_id": plan.vendor_bundle_id, "phone_number": "08012345678"})
                self.assertEqual(before - self.user.wallet_balance, plan.selling_price - plan.reward_amount)
                self.assertTrue(AirtimeTransaction.objects.filter(reference=result.json()["reference"], status="success", service_plan=plan).exists())

    def test_failed_data_purchase_returns_full_wallet_debit(self):
        plan = self.plans.first()
        response = Mock(headers={"Content-Type": "application/json"})
        response.json.return_value = {"status": "false", "message": "Unavailable"}
        before = self.user.wallet_balance
        with patch("store.views.requests.post", return_value=response):
            result = self.buy(plan)
        self.assertFalse(result.json()["status"])
        self.assertEqual(self.user.wallet_balance, before)

    def test_reapplying_catalogue_does_not_duplicate_plans_or_reduce_existing_prices(self):
        plan = self.plans.first()
        plan.selling_price += Decimal("100")
        plan.save()
        previous = plan.selling_price
        migration = importlib.import_module("store.migrations.0025_expand_available_data_catalogue")
        migration.expand_data(apps, SimpleNamespace(connection=SimpleNamespace(alias="default")))
        self.assertEqual(self.plans.count(), 47)
        plan.refresh_from_db()
        self.assertEqual(plan.selling_price, previous)
