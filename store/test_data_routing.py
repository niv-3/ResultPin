import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from store.data_routing import select_data_quote, total_supplier_cost
from store.models import (AirtimeTransaction, DataSupplier, ServiceCategory, ServicePlan,
                          ServiceProvider, SupplierQuote, User)
from store.models import Vendor


@override_settings(DYNAMIC_DATA_ROUTING=True, CHEAPDATAHUB_API_KEY="test-only",
    NELLOBYTE_USER_ID="test-account", NELLOBYTE_API_KEY="test-only",
    SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["testserver"], PAYSTACK_SECRET_KEY="sk_live_test_only")
class DataRoutingTests(TestCase):
    def setUp(self):
        self.cdh = Vendor.objects.create(name="CheapData")
        self.nello = Vendor.objects.create(name="Nellobyte")
        self.cdh_profile = DataSupplier.objects.create(vendor=self.cdh, adapter="cheapdata", enabled=True, funded=True)
        self.nello_profile = DataSupplier.objects.create(vendor=self.nello, adapter="nellobyte", enabled=True, funded=True)
        category = ServiceCategory.objects.create(name="Data", slug="internet-data")
        provider = ServiceProvider.objects.create(name="MTN", category=category, vendor=self.cdh)
        self.plan = ServicePlan.objects.create(provider=provider, name="1GB weekly", code="test-data",
            vendor_bundle_id=45, cost_price=450, selling_price=795)
        self.cdh_quote = SupplierQuote.objects.create(plan=self.plan, vendor=self.cdh, external_id="45",
            label="1GB weekly", cost=450, approved=True, available=True, checked_at=timezone.now())
        self.nello_quote = SupplierQuote.objects.create(plan=self.plan, vendor=self.nello, external_id="4",
            network_code="01", label="1GB - Weekly (SME Data)", cost=410,
            approved=True, available=True, checked_at=timezone.now())
        self.user = User.objects.create_user(username="router-test", email="router@example.invalid")
        self.user.credit_wallet(10000)
        self.client.force_login(self.user)

    def buy(self, method="wallet"):
        return self.client.post(f"/service/pay/internet-data/{self.plan.pk}/", data=json.dumps({
            "phone": "08012345678", "payment_method": method, "expected_price": "795",
        }), content_type="application/json")

    def test_lowest_total_cost_wins_without_changing_customer_price(self):
        self.assertEqual(select_data_quote(self.plan).pk, self.nello_quote.pk)
        self.nello_profile.purchase_fee = Decimal("50")
        self.nello_profile.save()
        self.assertEqual(select_data_quote(self.plan).pk, self.cdh_quote.pk)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.selling_price, 795)

    def test_ineligible_routes_are_excluded(self):
        for change in ({"approved": False}, {"available": False},
                       {"checked_at": timezone.now() - timedelta(hours=25)},
                       {"checked_at": timezone.now() + timedelta(hours=1)}, {"network_code": ""}):
            with self.subTest(change=change):
                SupplierQuote.objects.filter(pk=self.nello_quote.pk).update(**change)
                self.assertEqual(select_data_quote(self.plan).pk, self.cdh_quote.pk)
                self.nello_quote.save()
        for field in ("funded", "enabled"):
            setattr(self.nello_profile, field, False)
            self.nello_profile.save()
            self.assertEqual(select_data_quote(self.plan).pk, self.cdh_quote.pk)
            setattr(self.nello_profile, field, True)
        self.nello_profile.save()
        with override_settings(NELLOBYTE_API_KEY=""):
            self.assertEqual(select_data_quote(self.plan).pk, self.cdh_quote.pk)

    def test_no_profitable_offer_never_charges_or_calls_supplier(self):
        SupplierQuote.objects.update(cost=790)
        before = self.user.wallet_balance
        with patch("store.data_routing.requests.get") as vend:
            self.assertFalse(self.buy().json()["status"])
        vend.assert_not_called()
        self.assertEqual(before, self.user.wallet_balance)
        self.assertFalse(AirtimeTransaction.objects.exists())

    def test_nellobyte_checkout_uses_selected_id_and_snapshots_cost(self):
        response = Mock(status_code=200)
        response.json.return_value = {"status": "ORDER_COMPLETED", "statuscode": "200", "orderid": "supplier-123"}
        before = self.user.wallet_balance
        with patch("store.data_routing.requests.get", return_value=response) as vend, patch("store.data_routing.requests.post") as cdh:
            result = self.buy().json()
        self.assertTrue(result["status"])
        cdh.assert_not_called()
        self.assertEqual(vend.call_args.kwargs["params"]["DataPlan"], "4")
        self.assertEqual(vend.call_args.kwargs["params"]["MobileNetwork"], "01")
        order = AirtimeTransaction.objects.get(reference=result["reference"])
        self.assertEqual(order.supplier_vendor, self.nello)
        self.assertEqual(order.supplier_cost, Decimal("410"))
        self.assertEqual(order.supplier_total_cost, Decimal("422.30"))
        self.assertEqual(order.supplier_reference, "supplier-123")
        self.assertEqual(before - self.user.wallet_balance, self.plan.selling_price - self.plan.reward_amount)

    def test_timeout_holds_debit_and_never_falls_back(self):
        before = self.user.wallet_balance
        with patch("store.data_routing.requests.get", side_effect=requests.Timeout) as vend, patch("store.data_routing.requests.post") as fallback:
            result = self.buy().json()
        self.assertTrue(result["status"])
        self.assertIn("being confirmed", result["message"])
        self.assertEqual(vend.call_count, 1)
        fallback.assert_not_called()
        self.assertEqual(before - self.user.wallet_balance, self.plan.selling_price)
        self.assertEqual(AirtimeTransaction.objects.get().status, "pending")
        self.assertEqual(select_data_quote(self.plan).vendor_id, self.cdh.pk)

    def test_explicit_rejection_refunds_once_without_second_supplier(self):
        response = Mock(status_code=200)
        response.json.return_value = {"status": "INVALID_RECIPIENT"}
        before = self.user.wallet_balance
        with patch("store.data_routing.requests.get", return_value=response), patch("store.data_routing.requests.post") as fallback:
            self.assertFalse(self.buy().json()["status"])
        fallback.assert_not_called()
        self.assertEqual(before, self.user.wallet_balance)

    def test_card_route_is_pinned_and_duplicate_callback_does_not_revend(self):
        from store.views import complete_card_service_order
        with patch("store.views.initialize_paystack", return_value={"status": True, "data": {"authorization_url": "https://checkout.paystack.com/test"}}):
            self.assertTrue(self.buy("card").json()["status"])
        order = AirtimeTransaction.objects.get()
        self.assertEqual(order.supplier_adapter, "nellobyte")
        # A better offer appears after payment starts; the paid order must not switch.
        SupplierQuote.objects.filter(pk=self.cdh_quote.pk).update(cost=200)
        response = Mock(status_code=200)
        response.json.return_value = {"status": "ORDER_COMPLETED"}
        payment = {"status": "success", "reference": order.reference, "currency": "NGN", "amount": 79500}
        with patch("store.data_routing.requests.get", return_value=response) as vend:
            self.assertTrue(complete_card_service_order(order, payment))
            self.assertTrue(complete_card_service_order(order, payment))
        self.assertEqual(vend.call_count, 1)
        self.assertEqual(vend.call_args.kwargs["params"]["DataPlan"], "4")

    def test_unconfirmed_order_reconciles_without_repurchase_or_duplicate_cashback(self):
        with patch("store.data_routing.requests.get", side_effect=requests.Timeout):
            self.buy()
        order = AirtimeTransaction.objects.get()
        AirtimeTransaction.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(minutes=3))
        response = Mock(status_code=200)
        response.json.return_value = {"status": "ORDER_COMPLETED", "orderid": "confirmed-1"}
        with patch("store.management.commands.reconcile_data_orders.requests.get", return_value=response) as query:
            call_command("reconcile_data_orders", stdout=StringIO())
            call_command("reconcile_data_orders", stdout=StringIO())
        self.assertEqual(query.call_count, 1)
        self.assertIn("APIQueryV1", query.call_args.args[0])
        order.refresh_from_db()
        self.assertEqual(order.status, "success")
        self.assertEqual(self.user.wallet_transactions.filter(source="cashback_reward").count(), 1)

    def test_sync_cannot_approve_changed_label_or_change_retail_price(self):
        response = Mock(status_code=200)
        response.json.return_value = {"MOBILE_NETWORK": {"MTN": [{"ID": "01", "PRODUCT": [
            {"PRODUCT_CODE": "4", "PRODUCT_NAME": "1GB - Daily", "PRODUCT_AMOUNT": "390"}]}]}}
        with patch("store.management.commands.sync_supplier_quotes.requests.get", return_value=response):
            call_command("sync_supplier_quotes", supplier="nellobyte", stdout=StringIO())
        self.nello_quote.refresh_from_db()
        self.plan.refresh_from_db()
        self.assertFalse(self.nello_quote.approved)
        self.assertEqual(self.nello_quote.cost, 390)
        self.assertEqual(self.plan.selling_price, 795)

    def test_data_plan_does_not_require_a_cheapdata_id_when_dynamic(self):
        from store.views import listed_service_plans
        self.plan.vendor_bundle_id = None
        self.plan.save()
        self.assertTrue(listed_service_plans("internet-data").filter(pk=self.plan.pk).exists())
        response = Mock(status_code=200)
        response.json.return_value = {"status": "ORDER_COMPLETED"}
        with patch("store.data_routing.requests.get", return_value=response):
            self.assertTrue(self.buy().json()["status"])

    def test_cost_increase_before_card_delivery_refunds_without_vending(self):
        from store.views import complete_card_service_order
        with patch("store.views.initialize_paystack", return_value={"status": True, "data": {"authorization_url": "https://checkout.paystack.com/test"}}):
            self.buy("card")
        order = AirtimeTransaction.objects.get()
        SupplierQuote.objects.filter(pk=self.nello_quote.pk).update(cost=800)
        response = Mock(status_code=200)
        response.json.return_value = {"status": True}
        with patch("store.data_routing.requests.get") as vend, patch("store.views.requests.post", return_value=response) as refund:
            complete_card_service_order(order, {"status": "success", "reference": order.reference,
                "currency": "NGN", "amount": 79500})
        vend.assert_not_called()
        self.assertEqual(refund.call_args.args[0], "https://api.paystack.co/refund")
        order.refresh_from_db()
        self.assertEqual(order.status, "refund_pending")
