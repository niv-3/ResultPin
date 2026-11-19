from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from .data_reconciliation import data_response, reconcile_cheapdata
from .models import AirtimeTransaction, ServiceCategory, ServicePlan, ServiceProvider, User, WalletTransaction


@override_settings(CHEAPDATAHUB_API_KEY="test", SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["testserver"])
class DataReconciliationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="refund-test")
        category = ServiceCategory.objects.create(name="Data", slug="internet-data")
        provider = ServiceProvider.objects.create(name="MTN", category=category)
        self.plan = ServicePlan.objects.create(provider=provider, name="5GB SME (30 Days)", code="reconcile",
            selling_price=2300, cost_price=2050, vendor_bundle_id=50)
        self.user.credit_wallet(5000)
        self.order = AirtimeTransaction.objects.create(user=self.user, service_plan=self.plan,
            phone="08012345678", amount_paid=2300, reference="DATA-TEST", payment_method="wallet",
            supplier_cost=2050, cashback_snapshot=30, status="pending")
        AirtimeTransaction.objects.filter(pk=self.order.pk).update(created_at=timezone.now() - timedelta(minutes=3))
        self.order.refresh_from_db()
        self.user.debit_wallet(2300, reference=self.order.reference)
        self.row = {"item": "5GB mtn", "recipient": "08012345678", "amount": 2050,
            "tx_ref": "SUPPLIER-TEST", "completed": False, "category": "Failed - Refunded",
            "timein": self.order.created_at.isoformat()}

    def reconcile(self, rows=None):
        response = Mock(status_code=200)
        response.json.return_value = {"status": "true", "data": [self.row] if rows is None else rows}
        with patch("store.data_reconciliation.requests.get", return_value=response), patch("requests.post") as purchase:
            count = reconcile_cheapdata(self.user.pk)
            purchase.assert_not_called()
            return count

    def test_supplier_refund_restores_full_retail_once(self):
        self.assertEqual(self.reconcile(), 1)
        self.assertEqual(self.reconcile(), 0)
        self.assertEqual(self.user.wallet_balance, Decimal("5000"))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "failed")
        self.assertEqual(self.order.supplier_reference, "SUPPLIER-TEST")

    def test_manual_refund_is_not_credited_again(self):
        self.user.credit_wallet(2300, reference="REFUND-DATA-TEST")
        self.assertEqual(self.reconcile(), 1)
        self.assertEqual(self.user.wallet_balance, Decimal("5000"))

    def test_success_adds_cashback_once(self):
        self.row.update(category="Successful", completed=True)
        self.assertEqual(self.reconcile(), 1)
        self.assertEqual(self.reconcile(), 0)
        self.assertEqual(self.user.wallet_balance, Decimal("2730"))

    def test_incomplete_is_not_evidence_of_refund(self):
        self.row["category"] = "Processing"
        self.assertEqual(self.reconcile(), 0)
        self.assertEqual(self.user.wallet_balance, Decimal("2700"))

    def test_mismatched_amount_phone_size_or_time_stays_pending(self):
        for field, value in (("amount", 2000), ("recipient", "08011111111"),
                             ("item", "7GB mtn"), ("timein", timezone.now().isoformat())):
            with self.subTest(field=field):
                bad = {**self.row, field: value}
                self.assertEqual(self.reconcile([bad]), 0)

    def test_duplicate_supplier_matches_require_review(self):
        self.assertEqual(self.reconcile([self.row, {**self.row, "tx_ref": "OTHER"}]), 0)

    def test_competing_local_order_requires_review(self):
        AirtimeTransaction.objects.create(user=self.user, service_plan=self.plan, phone=self.order.phone,
            amount_paid=2300, supplier_cost=2050, reference="DATA-OTHER", created_at=self.order.created_at)
        AirtimeTransaction.objects.filter(reference="DATA-OTHER").update(created_at=self.order.created_at)
        self.assertEqual(self.reconcile(), 0)

    def test_response_retains_reference_unknown_and_http_errors_stay_pending(self):
        for status, http, expected in (("processing", 200, "pending"), ("true", 502, "pending"),
                                       ("false", 200, "failed"), ("true", 200, "success")):
            response = Mock(status_code=http)
            response.json.return_value = {"status": status, "reference": "SUPPLIER-TEST"}
            self.assertEqual(data_response(self.order, response)["status"], expected)
        self.order.refresh_from_db()
        self.assertEqual(self.order.supplier_reference, "SUPPLIER-TEST")

    def test_wallet_reconcile_is_user_scoped_and_post_only(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/wallet/reconcile-data/').status_code, 405)
        with patch('store.views.reconcile_cheapdata', return_value=1) as reconcile:
            self.assertTrue(self.client.post('/wallet/reconcile-data/').json()['updated'])
            reconcile.assert_called_once_with(self.user.pk)
            self.assertFalse(self.client.post('/wallet/reconcile-data/').json()['updated'])

    @override_settings(DYNAMIC_DATA_ROUTING=False, DATA_QUOTE_GUARD_ENABLED=False)
    def test_pending_order_blocks_duplicate_purchase_without_debit(self):
        import json
        self.client.force_login(self.user)
        with patch('store.views.requests.post') as supplier:
            result = self.client.post(f'/service/pay/internet-data/{self.plan.pk}/',
                data=json.dumps({'phone': self.order.phone, 'payment_method': 'wallet', 'expected_price': '2300'}),
                content_type='application/json').json()
        self.assertFalse(result['status'])
        self.assertIn('still being confirmed', result['message'])
        supplier.assert_not_called()
        self.assertEqual(self.user.wallet_balance, Decimal('2700'))
