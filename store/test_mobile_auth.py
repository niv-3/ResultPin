import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings

from core.session_pages import SessionPageCacheMiddleware
from store.views import custom_login, custom_logout


@override_settings(ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False)
class MobileAuthTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, method="get", data=None, authenticated=False):
        request = getattr(self.factory, method)(
            "/login/", data=data or {}, HTTP_ACCEPT="application/json"
        )
        request.user = SimpleNamespace(is_authenticated=True) if authenticated else AnonymousUser()
        return request

    def test_current_token_can_be_requested_without_database_or_login(self):
        response = custom_login(self.request())
        self.assertFalse(json.loads(response.content)["authenticated"])
        self.assertTrue(json.loads(response.content)["csrf_token"])
        self.assertIn("no-store", response["Cache-Control"])

    def test_back_to_login_keeps_existing_session(self):
        request = self.factory.get("/login/")
        request.user = SimpleNamespace(is_authenticated=True)
        response = custom_login(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")

    def test_signed_out_phone_home_redirects_to_login(self):
        response = self.client.get("/", HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 10) Mobile")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/login/")
        self.assertIn("no-store", response["Cache-Control"])

    def test_authenticated_json_refreshes_token(self):
        response = custom_login(self.request(authenticated=True))
        self.assertTrue(json.loads(response.content)["authenticated"])
        self.assertTrue(json.loads(response.content)["csrf_token"])

    def test_external_redirect_is_rejected(self):
        request = self.request(data={"next": "https://attacker.example"}, authenticated=True)
        self.assertEqual(json.loads(custom_login(request).content)["redirect"], "/")

    @patch("store.views.authenticate", return_value=None)
    def test_invalid_password_is_inline_error(self, authenticate):
        request = self.request("post", {"username": "test@example.com", "password": "wrong"})
        request._dont_enforce_csrf_checks = True
        response = custom_login(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn("incorrect", json.loads(response.content)["message"])

    @patch("store.views.login")
    @patch("store.views.authenticate", return_value=object())
    def test_mobile_login_returns_destination_without_redirect_post(self, authenticate, login):
        request = self.request("post", {"username": "08012345678", "password": "correct", "next": "/wallet/"})
        request._dont_enforce_csrf_checks = True
        response = custom_login(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["redirect"], "/wallet/")
        login.assert_called_once()

    @patch("store.views.logout")
    def test_get_logout_cannot_end_session(self, logout):
        response = custom_logout(self.factory.get("/logout/"))
        self.assertEqual(response.status_code, 405)
        logout.assert_not_called()

    def test_post_logout_requires_csrf(self):
        response = Client(enforce_csrf_checks=True).post("/logout/")
        self.assertEqual(response.status_code, 403)

    def test_login_post_still_requires_csrf(self):
        response = Client(enforce_csrf_checks=True).post("/login/", {"username": "test", "password": "test"})
        self.assertEqual(response.status_code, 403)

    def test_account_html_is_not_cached(self):
        request = self.request(authenticated=True)
        response = SessionPageCacheMiddleware(lambda request: HttpResponse("Account"))(request)
        self.assertIn("no-store", response["Cache-Control"])


@override_settings(
    ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False,
    STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
)
class MobileSessionFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from store.models import User
        cls.user = User.objects.create_user(
            username="mobile@example.invalid", email="mobile@example.invalid",
            phone="08012345678", password="Local-test-only-882!",
        )

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def token(self):
        return self.client.get("/login/", HTTP_ACCEPT="application/json").json()["csrf_token"]

    def sign_in(self, identifier="08012345678"):
        return self.client.post("/login/", {
            "username": identifier, "password": "Local-test-only-882!",
            "csrfmiddlewaretoken": self.token(),
        }, HTTP_ACCEPT="application/json")

    def test_phone_and_email_sign_in(self):
        for identifier in ("08012345678", "mobile@example.invalid"):
            with self.subTest(identifier=identifier):
                self.client = Client(enforce_csrf_checks=True)
                self.assertEqual(self.sign_in(identifier).status_code, 200)
                self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_back_and_old_logout_link_preserve_session(self):
        self.sign_in()
        self.assertRedirects(self.client.get("/login/"), "/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/logout/").status_code, 405)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_stale_token_rejected_then_refresh_allows_explicit_logout(self):
        old_token = self.token()
        self.sign_in()
        self.assertEqual(self.client.post("/logout/", {"csrfmiddlewaretoken": old_token}).status_code, 403)
        current = self.token()
        self.assertEqual(self.client.post("/logout/", {"csrfmiddlewaretoken": current}).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(self.client.get("/login/", HTTP_ACCEPT="application/json").json()["authenticated"])

    def test_repeat_sign_in_returns_existing_session(self):
        self.sign_in()
        response = self.client.post("/login/", {"csrfmiddlewaretoken": self.token()}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["authenticated"])

    def test_expired_session_returns_sign_in_state(self):
        self.sign_in()
        session = self.client.session
        session.flush()
        response = self.client.get("/login/", HTTP_ACCEPT="application/json")
        self.assertFalse(response.json()["authenticated"])

    def test_authenticated_home_and_templates_render_without_cache(self):
        self.sign_in()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(response, 'method="post" action="/logout/"')
        self.assertNotContains(response, 'href="/logout/"')

    def test_signed_in_phone_can_open_home(self):
        self.sign_in()
        self.assertEqual(self.client.get("/", HTTP_USER_AGENT="Android Mobile").status_code, 200)

    def test_desktop_home_remains_public(self):
        self.assertEqual(self.client.get("/", HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0)").status_code, 200)

    def test_admin_username_without_email_can_sign_in_to_admin(self):
        from store.models import User
        admin = User.objects.create_superuser(username="localadmin", email="", password="Local-test-only-882!")
        response = self.client.get("/admin/login/")
        token = response.context["csrf_token"]
        response = self.client.post("/admin/login/", {
            "username": "localadmin", "password": "Local-test-only-882!",
            "csrfmiddlewaretoken": token, "next": "/admin/",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), admin.pk)

    def test_admin_username_is_not_customer_sign_in(self):
        from store.models import User
        User.objects.create_superuser(username="localadmin", email="", password="Local-test-only-882!")
        response = self.client.post("/login/", {
            "username": "localadmin", "password": "Local-test-only-882!",
            "csrfmiddlewaretoken": self.token(),
        }, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("_auth_user_id", self.client.session)
