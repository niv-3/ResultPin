import time
from unittest.mock import patch

from django.test import TestCase, override_settings
from store.models import ServiceCategory, User


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["testserver"],
                   STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class IdleSessionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="idle-user", email="idle@example.com")
        self.client.force_login(self.user)
        self.now = int(time.time())

    def set_last(self, timestamp):
        session = self.client.session
        session["payvict_last_activity"] = timestamp
        session.save()

    def test_inactive_session_cannot_start_a_purchase(self):
        self.set_last(self.now - 61)
        with patch("store.bills.vtpass_post") as supplier:
            response = self.client.post("/service/pay/cable/", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()["authenticated"])
        self.assertNotIn("_auth_user_id", self.client.session)
        supplier.assert_not_called()

    def test_passive_auth_checks_and_prefetch_do_not_refresh_activity(self):
        last = self.now - 30
        self.set_last(last)
        self.client.get("/login/", HTTP_ACCEPT="application/json")
        self.assertEqual(self.client.session["payvict_last_activity"], last)
        self.client.get("/services/cable-tv/", HTTP_X_PAYVICT_PREFETCH="1")
        self.assertEqual(self.client.session["payvict_last_activity"], last)

    def test_real_activity_refreshes_session_before_expiry(self):
        self.set_last(self.now - 30)
        response = self.client.post("/session/activity/", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["authenticated"])
        self.assertGreaterEqual(self.client.session["payvict_last_activity"], self.now)
        self.assertEqual(self.client.session.get_expiry_age(), 60)

    def test_heartbeat_cannot_revive_expired_session(self):
        self.set_last(self.now - 61)
        response = self.client.post("/session/activity/", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 401)

    def test_blog_menu_uses_global_categories_and_includes_timeout_warning(self):
        ServiceCategory.objects.get_or_create(slug="electricity", defaults={"name": "Electricity", "is_active": True})
        response = self.client.get("/blog/")
        self.assertContains(response, 'id="idle-warning"')
        self.assertContains(response, 'href="/services/cable-tv/"')
        self.assertContains(response, 'href="/services/electricity/"')
        self.assertNotContains(response, "No services available")

    def test_provider_webhook_is_not_intercepted_by_browser_idle_expiry(self):
        self.set_last(self.now - 61)
        response = self.client.post("/paystack_webhook/", data="{}", content_type="application/json")
        self.assertNotEqual(response.status_code, 302)
        self.assertEqual(self.client.session["payvict_last_activity"], self.now - 61)
