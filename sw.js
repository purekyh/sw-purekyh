// Service Worker - 점령치킨각
const CACHE = 'jokbo-v1';
self.addEventListener('install', e => {
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  clients.claim();
});
self.addEventListener('fetch', e => {
  // Firebase는 캐시 안 함
  if(e.request.url.includes('firebase') || e.request.url.includes('discord')) return;
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});
