const CACHE='rootvalue-v2-20260818e';
const STATIC=['./','./index.html','./styles.css','./analysis.css','./rootvalue-v2.css','./app.js','./enhancements.js','./analysis.js','./polish.js','./manifest.json','./assets/rootvalue-mark.svg','./assets/vietnam-money-flow.svg'];
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(STATIC)));self.skipWaiting();});
self.addEventListener('activate',event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));self.clients.claim();});
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  const analytical=(url.pathname.includes('/data/')||url.pathname.includes('/content/')||url.pathname.includes('/config/'))&&url.pathname.endsWith('.json');
  if(analytical){
    event.respondWith(fetch(event.request,{cache:'no-store'}).then(res=>{const copy=res.clone();caches.open(CACHE).then(c=>c.put(event.request,copy));return res;}).catch(()=>caches.match(event.request)));
    return;
  }
  event.respondWith(caches.match(event.request).then(hit=>hit||fetch(event.request).then(res=>{const copy=res.clone();caches.open(CACHE).then(c=>c.put(event.request,copy));return res;})));
});
