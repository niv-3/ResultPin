from unittest.mock import Mock, patch

import requests
from django.test import TestCase, override_settings

from .models import AirtimeTransaction, ServiceCategory, ServiceProvider, ServicePlan, User
from .views import complete_card_service_order


@override_settings(PAYSTACK_SECRET_KEY="sk_live_mock")
class CardDeliveryFailureTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(username="card-refund")
        category = ServiceCategory.objects.create(name="Data", slug="internet-data")
        provider = ServiceProvider.objects.create(name="MTN", category=category)
        plan = ServicePlan.objects.create(provider=provider, name="6GB", code="card-six",
            selling_price=2785, cost_price=2500, vendor_bundle_id=53)
        self.order = AirtimeTransaction.objects.create(user=user, service_plan=plan,
            phone="08031234567", amount_paid=2785, reference="CARD-DATA-TEST",
            payment_method="card", status="pending")
        self.payment = {"status": "success", "reference": self.order.reference,
            "currency": "NGN", "amount": 278500}

    def test_explicit_http_rejection_requests_full_refund_once(self):
        rejection = Mock(status_code=400)
        rejection.json.return_value = {"status": "false", "message": "Rejected"}
        rejection.raise_for_status.side_effect = requests.HTTPError()
        refund = Mock(status_code=200)
        refund.json.return_value = {"status": True}
        with patch("store.views.requests.post", side_effect=[rejection, refund]) as post:
            complete_card_service_order(self.order, self.payment)
            complete_card_service_order(self.order, self.payment)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.args[0], "https://api.paystack.co/refund")
        self.assertEqual(post.call_args.kwargs["json"]["amount"], 278500)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "refund_pending")

    def test_delivery_timeout_does_not_refund_or_repurchase_blindly(self):
        with patch("store.views.requests.post", side_effect=requests.Timeout()) as post:
            complete_card_service_order(self.order, self.payment)
            complete_card_service_order(self.order, self.payment)
        self.assertEqual(post.call_count, 1)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "processing")

    def test_uncertain_refund_is_flagged_and_not_repeated(self):
        rejection = Mock(status_code=402)
        rejection.json.return_value = {"status": "false"}
        with patch("store.views.requests.post", side_effect=[rejection, requests.Timeout()]) as post:
            complete_card_service_order(self.order, self.payment)
            complete_card_service_order(self.order, self.payment)
        self.assertEqual(post.call_count, 2)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "refund_review")
