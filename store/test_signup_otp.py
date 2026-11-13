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
