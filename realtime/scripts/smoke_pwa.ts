/**
 * Bước smoke PWA (mọi profile, chỉ đọc): manifest (icon 192 / 512, standalone) + `sw.js` phục vụ đúng, không cache
 * immutable (trình duyệt phải luôn lấy bản service worker mới).
 */

import { type CallOptions, expect, type Reply } from "./smoke_io.ts";

type Call = (method: "GET" | "POST", path: string, o?: CallOptions) => Promise<Reply>;

export interface PwaDeps {
  step: (name: string, fn: () => Promise<void>) => void;
  call: Call;
  base: string;
}

export function addPwaSteps(d: PwaDeps): void {
  d.step("PWA — manifest (icon 192 / 512, standalone) + sw.js phục vụ đúng", async () => {
    const m = await fetch(`${d.base}/manifest.webmanifest`);
    expect(m.status === 200, `/manifest.webmanifest → ${m.status}`);
    const manifest = (await m.json()) as { display?: string; icons?: { sizes: string }[] };
    const sizes = (manifest.icons ?? []).map((i) => i.sizes);
    expect(manifest.display === "standalone" && sizes.includes("192x192") && sizes.includes("512x512"), `manifest ${JSON.stringify(manifest).slice(0, 200)}`);
    const sw = await fetch(`${d.base}/sw.js`);
    const text = await sw.text();
    expect(sw.status === 200 && text.includes("addEventListener(\"fetch\"") && !(sw.headers.get("cache-control") ?? "").includes("immutable"), `/sw.js → ${sw.status}`);
  });
}
