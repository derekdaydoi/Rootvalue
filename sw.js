const CACHE_NAME = 'rootvalue-v3-20260820a';
const CACHE_PREFIX = 'rootvalue-';
const SHELL_ASSETS = [
  './',
  './index.html',
  './styles.css',
  './analysis.css',
  './rootvalue-v2.css',
  './app.js',
  './enhancements.js',
  './analysis.js',
  './polish.js',
  './health-ui.js',
  './manifest.json',
  './assets/rootvalue-mark.svg',
  './assets/vietnam-money-flow.svg',
];
const DATA_ASSETS = [
  './data/rootvalue.json',
  './data/market.json',
  './data/global.json',
  './data/company_dashboard.json',
  './content/knowledge.json',
];
const SHELL_URLS = new Set(SHELL_ASSETS.map(path => new URL(path, self.registration.scope).href));

function isDataRequest(url) {
  return url.pathname.endsWith('.json') &&
    ['/data/', '/content/', '/config/'].some(segment => url.pathname.includes(segment));
}

function normalizedDataRequest(request) {
  const url = new URL(request.url);
  url.searchParams.delete('t');
  return new Request(url.href, request);
}

async function putIfOk(cacheKey, response) {
  if (!response || !response.ok) return;
  const cache = await caches.open(CACHE_NAME);
  await cache.put(cacheKey, response.clone());
}

async function networkFirst(request, cacheKey, fallbackKey) {
  try {
    const response = await fetch(request, {cache: 'no-store'});
    if (response.ok) {
      await putIfOk(cacheKey, response);
      return response;
    }
    return (await caches.match(cacheKey)) || response;
  } catch (_) {
    const cached = await caches.match(cacheKey);
    if (cached) return cached;
    if (fallbackKey) {
      const fallback = await caches.match(fallbackKey);
      if (fallback) return fallback;
    }
    return Response.error();
  }
}

async function staleWhileRevalidate(event, request) {
  const cachedRequest = caches.match(request);
  const refresh = fetch(request, {cache: 'no-cache'}).then(async response => {
    await putIfOk(request, response);
    return response;
  });
  event.waitUntil(refresh.catch(() => undefined));

  const cached = await cachedRequest;
  if (cached) {
    return cached;
  }

  try {
    return await refresh;
  } catch (_) {
    return Response.error();
  }
}

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    // The first page load is not yet controlled by this worker, so data must be
    // seeded during install for offline use immediately after that first visit.
    await cache.addAll([...SHELL_ASSETS, ...DATA_ASSETS]);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys
      .filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
      .map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const {request} = event;
  const url = new URL(request.url);

  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(request, request, new URL('./index.html', self.registration.scope).href));
    return;
  }

  if (isDataRequest(url)) {
    event.respondWith(networkFirst(request, normalizedDataRequest(request)));
    return;
  }

  const shellUrl = new URL(request.url);
  shellUrl.search = '';
  if (SHELL_URLS.has(shellUrl.href)) {
    event.respondWith(staleWhileRevalidate(event, request));
  }
});
