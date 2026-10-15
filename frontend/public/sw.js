/* BizWithAgents service worker (PWA): cache file tĩnh để mở app nhanh / cài được; KHÔNG BAO GIỜ cache API / socket.
 * - Điều hướng (HTML): mạng trước, mất mạng → index.html đã cache (app tự báo lỗi mạng khi gọi API).
 * - /assets/* (tên có hash, bất biến): cache trước.
 * - File tĩnh khác cùng origin (icon, manifest): dùng cache, làm mới nền.
 * Đổi cấu trúc cache → tăng VERSION (cache cũ bị xoá khi SW mới kích hoạt). */
const VERSION = "v1";
const SHELL = `bw-shell-${VERSION}`;
const ASSETS = `bw-assets-${VERSION}`;
const PRECACHE = ["/", "/index.html", "/manifest.webmanifest", "/favicon.svg", "/brand/icon-192.png", "/brand/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("bw-") && k !== SHELL && k !== ASSETS).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

const isDynamic = (url) => /\/(api|ws)\//.test(url.pathname) || url.pathname.endsWith("/sw.js");

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || isDynamic(url)) return;
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(SHELL).then((cache) => cache.put("/index.html", copy));
          return res;
        })
        .catch(() => caches.match("/index.html")),
    );
    return;
  }
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(ASSETS).then((cache) => cache.put(req, copy));
            }
            return res;
          }),
      ),
    );
    return;
  }
  event.respondWith(
    caches.match(req).then((hit) => {
      const fresh = fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(SHELL).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(() => hit);
      return hit || fresh;
    }),
  );
});

/* Thông báo đẩy (Web Push): nội dung đã giải mã {id, kind, title, body, url}. App đang hiện trên màn hình → bỏ qua vì
 * app đã có toast (trừ iPhone / iPad: Safari bắt mọi push phải hiện thông báo). Bấm thông báo → mở / focus đúng trang. */
const IOS = /iPhone|iPad|iPod/.test(self.navigator.userAgent) || (/Macintosh/.test(self.navigator.userAgent) && self.navigator.maxTouchPoints > 1);

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { title: event.data ? event.data.text() : "" };
  }
  const options = {
    body: data.body || "",
    icon: "/brand/icon-192.png",
    badge: "/brand/icon-192.png",
    tag: data.id || data.kind || "bizwithagents",
    data: { url: data.url || "/notifications" },
  };
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      if (!IOS && wins.some((w) => w.visibilityState === "visible")) return undefined;
      return self.registration.showNotification(data.title || "BizWithAgents", options);
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      const win = wins.find((w) => "focus" in w);
      if (!win) return self.clients.openWindow(url);
      return win.focus().then((w) => (w && "navigate" in w ? w.navigate(url).catch(() => w) : w));
    }),
  );
});
