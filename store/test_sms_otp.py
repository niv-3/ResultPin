import time
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model

from store.sms_otp import send_sms_otp


@override_settings(SMS_OTP_ENABLED=True, TERMII_API_KEY='test-key', TERMII_SENDER_ID='Payvict',
                   TERMII_BASE_URL='https://api.ng.termii.com', SMS_OTP_HOURLY_LIMIT=20)
class SmsProviderTests(TestCase):
    @patch('store.sms_otp.requests.post')
    def test_nigerian_number_format_and_shared_send_limit(self, post):
        post.return_value = Mock(json=lambda: {'message_id': 'accepted'})
        for _ in range(3):
            send_sms_otp('08012345678', '123456')
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['to'], '2348012345678')
        self.assertEqual(payload['channel'], 'dnd')
        self.assertIn('123456', payload['sms'])
        with self.assertRaises(OSError):
            send_sms_otp('08012345678', '999999')
        self.assertEqual(post.call_count, 3)

    @override_settings(SMS_OTP_HOURLY_LIMIT=1)
    @patch('store.sms_otp.requests.post')
    def test_global_budget_caps_different_numbers(self, post):
        post.return_value = Mock(json=lambda: {'message_id': 'accepted'})
        send_sms_otp('08012345678', '123456')
        with self.assertRaises(OSError):
            send_sms_otp('08012345679', '123456')
        self.assertEqual(post.call_count, 1)

    @override_settings(TERMII_BASE_URL='https://example.com')
    @patch('store.sms_otp.requests.post')
    def test_keys_cannot_be_sent_to_an_unapproved_host(self, post):
        with self.assertRaises(OSError):
            send_sms_otp('08012345678', '123456')
        post.assert_not_called()

    @patch('store.sms_otp.requests.post')
    def test_rejected_message_is_not_treated_as_sent(self, post):
        post.return_value = Mock(json=lambda: {'message': 'Rejected'})
        with self.assertRaises(OSError):
            send_sms_otp('08012345678', '123456')


@override_settings(SMS_OTP_ENABLED=True, TERMII_API_KEY='test', TERMII_SENDER_ID='Payvict',
                   TERMII_BASE_URL='https://api.ng.termii.com', ALLOWED_HOSTS=['testserver'],
                   SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False,
                   STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                             'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class PhoneSignupTests(TestCase):
    def signup(self):
        with patch('store.views.send_sms_otp'):
            return self.client.post('/register/', {'email': 'signup@example.com', 'phone': '08012345678',
                'password': 'Strong-pass731!', 'password2': 'Strong-pass731!', 'otp_channel': 'sms'})

    def test_phone_code_and_explicit_email_fallback(self):
        self.signup()
        data = self.client.session['pending_user']
        self.assertEqual(data['otp_channel'], 'sms')
        response = self.client.get('/verify-otp/')
        self.assertContains(response, 'Verify your phone')
        self.assertContains(response, 'ending 5678')
        session = self.client.session
        session['pending_user'] = dict(data, otp='000000', last_sent_at=int(time.time()) - 61)
        session.save()
        with patch('store.views.send_otp') as email:
            self.client.post('/resend-otp/', {'otp_channel': 'email'})
            email.assert_called_once()
        self.assertEqual(self.client.session['pending_user']['otp_channel'], 'email')
        self.assertNotEqual(self.client.session['pending_user']['otp'], '000000')

    def test_quick_resends_do_not_spend_sms_credit(self):
        self.signup()
        with patch('store.views.send_sms_otp') as sms:
            self.client.post('/resend-otp/')
        sms.assert_not_called()

    def test_sms_code_completes_signup_and_phone_login(self):
        self.signup()
        code = self.client.session['pending_user']['otp']
        self.assertEqual(self.client.post('/verify-otp/', {'otp': code}).url, '/')
        user = get_user_model().objects.get(phone='08012345678')
        self.assertTrue(user.check_password('Strong-pass731!'))

    def test_sms_failure_does_not_create_an_account_or_pending_code(self):
        with patch('store.views.send_sms_otp', side_effect=OSError('Unavailable')):
            response = self.client.post('/register/', {'email': 'signup@example.com', 'phone': '08012345678',
                'password': 'Strong-pass731!', 'password2': 'Strong-pass731!', 'otp_channel': 'sms'})
        self.assertEqual(response.url, '/register/')
        self.assertNotIn('pending_user', self.client.session)
        self.assertFalse(get_user_model().objects.filter(phone='08012345678').exists())
