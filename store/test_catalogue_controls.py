import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings

from store.bills import available_options
from store.models import ServiceCategory, ServicePlan, ServiceProvider, User
from store.views import initiate_service_payment


class CatalogueControlsTests(TestCase):
    def test_paused_category_or_provider_blocks_stale_checkout(self):
        category = ServiceCategory.objects.create(name="Airtime", slug="paused-airtime", is_active=False)
        provider = ServiceProvider.objects.create(name="MTN", category=category)
        plan = ServicePlan.objects.create(provider=provider, name="100", code="paused-test", selling_price=100)
        for category_active, provider_active in [(False, True), (True, False)]:
            category.is_active = category_active
            category.save()
            provider.is_active = provider_active
            provider.save()
            request = RequestFactory().post("/service/pay/airtime/1/", data=json.dumps({
                "phone": "08012345678", "payment_method": "wallet"
            }), content_type="application/json")
            request.user = SimpleNamespace(is_authenticated=True)
            request._dont_enforce_csrf_checks = True
            with patch("store.views.purchase_airtime") as purchase:
                response = initiate_service_payment(request, plan.pk)
            self.assertEqual(response.status_code, 503)
            purchase.assert_not_called()

    @override_settings(VTPASS_TEST_MODE=False)
    def test_live_electricity_includes_aba_and_enugu_but_not_kano(self):
        category, _ = ServiceCategory.objects.update_or_create(slug="electricity", defaults={"name": "Electricity", "is_active": True})
        for code in ["aba-electric", "enugu-electric", "kano-electric"]:
            ServiceProvider.objects.create(name=code, category=category, vtpass_service_id=code)
        codes = set(available_options("electricity").values_list("vtpass_service_id", flat=True))
        self.assertTrue({"aba-electric", "enugu-electric"}.issubset(codes))
        self.assertNotIn("kano-electric", codes)

    @override_settings(VTPASS_BILLS_ENABLED=True, VTPASS_API_KEY="test", VTPASS_SECRET_KEY="test",
                       STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
                       SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["testserver"])
    def test_cable_screen_lists_each_provider_separately_and_is_not_cached(self):
        category, _ = ServiceCategory.objects.update_or_create(slug="cable-tv", defaults={"name": "Cable TV", "is_active": True})
        for name in ["DStv", "GOtv", "StarTimes"]:
            provider = ServiceProvider.objects.create(name=name, category=category, vtpass_service_id=name.lower())
            ServicePlan.objects.create(provider=provider, name="Basic", code="tv-test-" + name,
                                       vtpass_variation_code="basic", selling_price=4000)
        user = User.objects.create_user(username="tv-test-user", email="tv@example.com")
        self.client.force_login(user)
        response = self.client.get("/services/cable-tv/")
        self.assertEqual(response.status_code, 200)
        for name in ["DStv", "GOtv", "StarTimes"]:
            self.assertContains(response, name)
        self.assertContains(response, 'id="tv-provider"')
        self.assertContains(response, "data-service-init")
        self.assertIn("no-store", response["Cache-Control"])
