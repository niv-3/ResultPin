// Keep payments and private account pages network-only. Never cache customer data.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || event.request.mode !== 'navigate') return;
  event.respondWith(fetch(event.request).catch(() => new Response(
    '<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Payvict · Offline</title><body style="font:18px system-ui;padding:32px;color:#0b2c3d"><h1>You’re offline</h1><p>Connect to the internet to use Payvict.</p><button onclick="location.reload()" style="padding:12px 20px">Try again</button></body></html>',
    {status: 503, headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'}}
  )));
});
