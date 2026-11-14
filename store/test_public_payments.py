from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, override_settings

from core.preview import PreviewPaymentsMiddleware


@override_settings(BETA_PAYMENTS_ENABLED=True, BETA_BUYER_EMAILS=set(), VTPASS_BILLS_ENABLED=True)
class PublicPaymentsTests(SimpleTestCase):
    def setUp(self):
        self.middleware = PreviewPaymentsMiddleware(lambda request: None)

    def check(self, route, user):
        request = RequestFactory().post('/')
        request.user = user
        request.resolver_match = SimpleNamespace(url_name=route)
        return self.middleware.process_view(request, None, (), {})

    def test_registered_customer_needs_no_invitation_or_email(self):
        for email in ('new-customer@example.com', ''):
            for route in self.middleware.buyer_routes | self.middleware.bill_routes:
                with self.subTest(email=email, route=route):
                    self.assertIsNone(self.check(route, SimpleNamespace(is_authenticated=True, email=email)))

    def test_sign_in_is_still_required(self):
        for route in self.middleware.buyer_routes | self.middleware.bill_routes:
            with self.subTest(route=route):
                self.assertEqual(self.check(route, AnonymousUser()).status_code, 401)

    @override_settings(BETA_PAYMENTS_ENABLED=False)
    def test_payment_pause_still_blocks_all_purchase_routes(self):
        for route in self.middleware.buyer_routes | self.middleware.bill_routes:
            with self.subTest(route=route):
                self.assertEqual(self.check(route, SimpleNamespace(is_authenticated=True)).status_code, 503)

    @override_settings(VTPASS_BILLS_ENABLED=False)
    def test_provider_pause_still_blocks_bills(self):
        for route in self.middleware.bill_routes:
            with self.subTest(route=route):
                self.assertEqual(self.check(route, SimpleNamespace(is_authenticated=True)).status_code, 503)

    def test_withdrawal_routes_remain_disabled(self):
        for route in self.middleware.paused_routes:
            with self.subTest(route=route):
                self.assertEqual(self.check(route, SimpleNamespace(is_authenticated=True)).status_code, 503)

    def test_settlement_routes_do_not_require_an_invitation_or_session(self):
        for route in self.middleware.settlement_routes:
            with self.subTest(route=route):
                self.assertIsNone(self.check(route, AnonymousUser()))
