// Minimal service worker so Android offers "Install app". No offline cache: the app is useless without the server anyway.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
