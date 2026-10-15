/// <reference types="vitest/config" />
// Unit `.ts` chạy môi trường node; file cần DOM khai `// @vitest-environment jsdom` ở dòng đầu.
import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": resolve(import.meta.dirname, "src") } },
  test: {
    environment: "node",
    include: ["test/**/*.test.{ts,tsx}"],
    setupFiles: ["test/setup.ts"],
    env: { VITE_API_BASE_URL: "/bizwithagents/api", VITE_WS_PATH: "/bizwithagents/ws" },
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      // Primitive Radix chép nguyên (chỉ bọc class) — đo phần logic: lib, features, layout, pages, ui/shared.
      exclude: ["src/main.tsx", "src/ui/*.tsx", "src/lib/api/schema.d.ts"],
      thresholds: { lines: 80 },
    },
  },
});
