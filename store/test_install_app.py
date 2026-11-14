import json

from django.test import SimpleTestCase, override_settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static


@override_settings(ALLOWED_HOSTS=['testserver'], SECURE_SSL_REDIRECT=False)
class AppInstallTests(SimpleTestCase):
    def test_manifest_has_home_screen_icons(self):
        response = self.client.get('/manifest.webmanifest')
        self.assertEqual(response.status_code, 200)
        manifest = json.loads(response.content)
        self.assertEqual(manifest['name'], 'Payvict')
        self.assertEqual(manifest['display'], 'standalone')
        self.assertEqual(manifest['scope'], '/')
        self.assertEqual({icon['sizes'] for icon in manifest['icons']}, {'192x192', '512x512'})
        for asset in ('payvict-app-192.png', 'payvict-app-512.png'):
            self.assertIsNotNone(finders.find('store/images/' + asset))

    def test_login_offers_install_without_registration(self):
        response = self.client.get('/login/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Install app')
        self.assertContains(response, static('store/js/install-app.js'))
        self.assertContains(response, 'aria-labelledby="payvict-install-title"')

    def test_root_service_worker_is_javascript_and_never_caches_account_data(self):
        response = self.client.get('/service-worker.js')
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/javascript', response['Content-Type'])
        self.assertContains(response, "event.request.method !== 'GET'")
        self.assertContains(response, "event.request.mode !== 'navigate'")
        self.assertNotContains(response, 'caches.')
