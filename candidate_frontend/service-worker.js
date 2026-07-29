"use strict";

// Session profile UI revision: 2026-07-29.

const CACHE_PREFIX = "yanchushuxing-candidate-";
const CACHE_NAME = `${CACHE_PREFIX}v2`;
const STATIC_ASSETS = [
  "/candidate/assets/styles.css",
  "/candidate/assets/app.js",
  "/candidate/assets/result_adapter.js",
  "/candidate/assets/result_contract.json",
  "/candidate/assets/echarts.min.js",
  "/candidate/assets/manifest.webmanifest",
  "/candidate/assets/icons/icon.svg",
  "/candidate/assets/icons/icon-maskable.svg",
];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys
          .filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
          .map(key => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);

  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (request.method !== "GET" || !url.pathname.startsWith("/candidate/assets/")) return;

  event.respondWith(
    fetch(request)
      .then(response => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});
