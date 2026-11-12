from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch

from django.core import signing
from django.test import TestCase, override_settings

from store.models import CableTransaction, ServicePlan, User


@override_settings(VTPASS_BILLS_ENABLED=True, VTPASS_API_KEY="test", VTPASS_SECRET_KEY="test",
                   SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["testserver"])
class TVCheckoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tv-buyer", email="tv-buyer@example.com")
        self.user.credit_wallet(5000000)
        self.client.force_login(self.user)

    def checkout(self, plan, total=None):
        reference = uuid4().hex
        response = self.client.post("/service/pay/cable/", {
            "checkout": signing.dumps([self.user.pk, "cable", reference], salt="bill-checkout"),
            "selection": plan.pk, "account_number": "1234567890", "phone": "08012345678",
            "expected_total": str(plan.selling_price if total is None else total),
        })
        return reference, response

    def test_every_imported_package_splits_fee_and_vends_only_face_value(self):
        plans = ServicePlan.objects.filter(code__startswith="VTP-TV-", is_active=True).select_related("provider")
        self.assertEqual(plans.count(), 47)
        for plan in plans:
            with self.subTest(plan=plan.code):
                before = self.user.wallet_balance
                with patch("store.bills.variation_price_available", return_value=True) as verify_price, patch(
                    "store.bills.vtpass_post", side_effect=[
                        {"code": "000", "content": {"Customer_Name": "Test Customer"}},
                        {"code": "000", "content": {"transactions": {"status": "delivered"}}},
                    ]
                ) as api:
                    reference, response = self.checkout(plan)
                self.assertEqual(response.status_code, 302)
                bill = CableTransaction.objects.get(reference=reference)
                self.assertEqual(bill.status, "success")
                self.assertEqual(before - self.user.wallet_balance, plan.selling_price)
                self.assertEqual(bill.package_amount + bill.service_fee, bill.amount_paid)
                verify_price.assert_called_once_with(plan.provider.vtpass_service_id, plan.vtpass_variation_code, plan.market_price)
                payload = api.call_args_list[-1].args[1]
                self.assertEqual(payload["serviceID"], plan.provider.vtpass_service_id)
                if plan.provider.vtpass_service_id == "startimes":
                    self.assertNotIn("amount", payload)
                    self.assertNotIn("subscription_type", payload)
                else:
                    self.assertEqual(Decimal(str(payload["amount"])), plan.market_price)
                self.assertGreaterEqual(plan.selling_price * Decimal("0.945") - plan.cost_price, 30)

    def test_stale_total_does_not_charge_or_contact_supplier(self):
        plan = ServicePlan.objects.filter(code__startswith="VTP-TV-", is_active=True).first()
        before = self.user.wallet_balance
        with patch("store.bills.vtpass_post") as api:
            reference, _ = self.checkout(plan, total="1")
        api.assert_not_called()
        self.assertFalse(CableTransaction.objects.filter(reference=reference).exists())
        self.assertEqual(self.user.wallet_balance, before)

    def test_failed_purchase_refunds_package_and_fee_once(self):
        plan = ServicePlan.objects.filter(code__startswith="VTP-TV-", is_active=True).first()
        before = self.user.wallet_balance
        with patch("store.bills.variation_price_available", return_value=True), patch(
            "store.bills.vtpass_post", side_effect=[
                {"code": "000", "content": {"Customer_Name": "Test Customer"}}, {"code": "016"}
            ]
        ):
            reference, _ = self.checkout(plan)
        bill = CableTransaction.objects.get(reference=reference)
        self.assertEqual(bill.status, "failed")
        self.assertEqual(self.user.wallet_balance, before)
        from store.bills import settle_bill
        settle_bill(bill, {"code": "016"})
        self.assertEqual(self.user.wallet_balance, before)
