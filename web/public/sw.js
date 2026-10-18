// Keeps a copy of what the app fetches, so a course opened once still reads without a connection. Asking the
// tutor and sending answers still need the server.
const CACHE = 'wise-scholar'
const SHELL = '/'
// past this wait a stored copy is shown: a connection that is up but carries nothing would hang the page
const PATIENCE = 6000
// large downloads are fetched when asked for, never kept
const UNKEPT = /^(audio|video)\/|^application\/(pdf|zip)/

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.add(SHELL)))
  self.skipWaiting()
})

self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  // the warm-up check decides from the learner's latest activity; an old copy would offer one that is not due
  if (url.origin !== location.origin || url.pathname.startsWith('/mcp') || url.pathname.endsWith('/warmup')) return
  // live course events and partial audio responses cannot be stored
  if (request.headers.get('accept')?.includes('text/event-stream') || request.headers.has('range')) return
  // every route lives behind the hash, so the app shell is the one page load to keep
  if (request.mode === 'navigate' && url.pathname !== SHELL) return
  if (url.pathname.startsWith('/assets/')) event.respondWith(cacheFirst(request))
  else event.respondWith(networkFirst(request))
})

function keep(cache, request, response) {
  if (!UNKEPT.test(response.headers.get('content-type') ?? '')) cache.put(request, response).catch(() => {})
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE)
  const cached = await cache.match(request)
  if (cached) return cached
  const response = await fetch(request)
  if (response.ok) keep(cache, request, response.clone())
  return response
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE)
  const cached = await cache.match(request)
  // a copy to compare with, since the cached response itself may be handed to the page
  const old = request.mode === 'navigate' ? cached?.clone() : undefined
  // the shell revalidates, so a new build is picked up whatever the HTTP cache holds
  const network = fetch(request, request.mode === 'navigate' ? { cache: 'no-cache' } : {}).then(async (response) => {
    if (response.ok) {
      if (request.mode === 'navigate') await prune(cache, old, response.clone())
      keep(cache, request, response.clone())
    } else if (response.status === 404) cache.delete(request)
    // a server that is down behind the proxy answers 502 to a phone that is online
    else if (response.status >= 500 && cached) return cached
    return response
  })
  if (!cached) return network
  const late = new Promise((resolve) => setTimeout(() => resolve(cached), PATIENCE))
  return Promise.race([network.catch(() => cached), late])
}

/** A new build's shell names its hashed assets; the old build's that it no longer names are dropped, so unchanged
 * library chunks stay, and the new ones are fetched on use. */
async function prune(cache, old, fresh) {
  const entry = (html) => html.match(/\/assets\/index-[^"]+\.js/)?.[0]
  const html = await fresh.text()
  if (!old || entry(await old.text()) === entry(html)) return
  const named = new Set(html.match(/\/assets\/[^"]+/g))
  for (const request of await cache.keys()) {
    const { pathname } = new URL(request.url)
    if (pathname.startsWith('/assets/') && !named.has(pathname)) await cache.delete(request)
  }
}
