import time
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.contrib.auth import get_user_model

@override_settings(ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, STORAGES={"default":{"BACKEND":"django.core.files.storage.FileSystemStorage"},"staticfiles":{"BACKEND":"django.contrib.staticfiles.storage.StaticFilesStorage"}})
class SignupOtpTests(TestCase):
    def signup(self):
        with patch("store.views.send_otp"):
            return self.client.post("/register/", {"email":"signup@example.com", "phone":"08012345678", "first_name":"Test", "password":"Strong-pass731!", "password2":"Strong-pass731!"})

    def test_signup_resets_short_session_and_hashes_password(self):
        session=self.client.session
        session.set_expiry(60)
        session.save()
        self.assertEqual(self.signup().url, "/verify-otp/")
        session=self.client.session
        self.assertEqual(session.get_expiry_age(), 3600)
        self.assertNotIn("password", session["pending_user"])
        self.assertIn("no-store", self.client.get("/verify-otp/")["Cache-Control"])

    def test_expiry_preserves_details_and_resend_recovers(self):
        self.signup()
        session=self.client.session
        data=session["pending_user"]
        old=data["otp"]
        data["expires_at"]=int(time.time())-1
        session["pending_user"]=data
        session.save()
        self.assertEqual(self.client.post("/verify-otp/", {"otp":old}).url, "/verify-otp/")
        self.assertIn("pending_user", self.client.session)
        self.assertFalse(get_user_model().objects.filter(email=data["email"]).exists())
        with patch("store.views.send_otp") as send:
            self.client.post("/resend-otp/")
            send.assert_called_once()
        self.assertGreater(self.client.session["pending_user"]["expires_at"], time.time()+590)
        code=self.client.session["pending_user"]["otp"]
        self.assertEqual(self.client.post("/verify-otp/", {"otp":code}).url, "/")
        user=get_user_model().objects.get(email=data["email"])
        self.assertTrue(user.check_password("Strong-pass731!"))
        self.assertNotIn("pending_user", self.client.session)

    def test_wrong_codes_remain_limited(self):
        self.signup()
        for _ in range(5):
            response=self.client.post("/verify-otp/", {"otp":"invalid"})
        self.assertEqual(response.url, "/register/")
        self.assertNotIn("pending_user", self.client.session)

    def test_countdown_uses_original_expiry_on_reload(self):
        self.signup()
        session=self.client.session
        data=session["pending_user"]
        data["expires_at"]=int(time.time())+35
        session["pending_user"]=data
        session.save()
        response=self.client.get("/verify-otp/")
        self.assertLessEqual(response.context["otp_expires_at"]-response.context["otp_server_now"],35)
        self.assertNotContains(response,"let remainingSeconds = 600")

    def test_resend_requires_post_and_csrf(self):
        self.assertEqual(self.client.get("/resend-otp/").status_code,405)
        self.assertEqual(Client(enforce_csrf_checks=True).post("/resend-otp/").status_code,403)

    def test_missing_session_redirects_safely(self):
        self.assertEqual(self.client.get("/verify-otp/").url,"/register/")

    def test_validation_error_preserves_contact_fields_but_not_password(self):
        payload = {"email": "signup@example.com", "phone": "08012345678",
                   "first_name": "Test", "last_name": "Buyer",
                   "password": "Strong-pass731!", "password2": "different"}
        with patch("store.views.send_otp") as send:
            with self.assertLogs("payvict.auth", level="WARNING") as logs:
                response = self.client.post("/register/", payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwords do not match.")
        self.assertContains(response, 'value="signup@example.com"')
        self.assertContains(response, 'value="08012345678"')
        self.assertContains(response, 'value="Buyer"')
        self.assertNotContains(response, "Strong-pass731!")
        self.assertNotIn("pending_user", self.client.session)
        self.assertNotIn("signup@example.com", str(logs.output))
        send.assert_not_called()

    def test_delivery_failure_preserves_form_without_creating_account(self):
        with patch("store.views.send_otp", side_effect=OSError("provider unavailable")):
            response = self.client.post("/register/", {"email": "signup@example.com",
                "phone": "08012345678", "first_name": "Test",
                "password": "Strong-pass731!", "password2": "Strong-pass731!"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="signup@example.com"')
        self.assertContains(response, "We couldn&#x27;t send your code")
        self.assertFalse(get_user_model().objects.filter(email="signup@example.com").exists())

    def test_signup_verification_then_phone_and_email_login(self):
        self.signup()
        code = self.client.session["pending_user"]["otp"]
        self.assertEqual(self.client.post("/verify-otp/", {"otp": code}).status_code, 302)
        for identifier in ("08012345678", "+2348012345678", "signup@example.com"):
            self.client.logout()
            response = self.client.post("/login/", {"username": identifier,
                "password": "Strong-pass731!"}, HTTP_ACCEPT="application/json")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["authenticated"])
