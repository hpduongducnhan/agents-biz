import { resolve } from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

const repoRoot = resolve(import.meta.dirname, "..");

export default defineConfig(({ mode }) => {
  // Cùng file .env gốc với backend / realtime: VITE_* cho app, còn lại cho dev proxy.
  const env = loadEnv(mode, repoRoot, "");
  const clean = (v: string | undefined) => (v ?? "").replace(/\s+#.*$/, "").trim();
  const servicePath = clean(env.SERVICE_PATH) || "bizwithagents";
  const api = `http://localhost:${clean(env.PORT) || "8202"}`;
  const realtime = `http://localhost:${clean(env.REALTIME_PORT) || "8203"}`;
  return {
    envDir: repoRoot,
    plugins: [react(), tailwindcss()],
    resolve: { alias: { "@": resolve(import.meta.dirname, "src") } },
    server: {
      port: Number(clean(env.FRONTEND_PORT) || 8201),
      proxy: {
        [`/${servicePath}/api`]: { target: api, changeOrigin: true },
        [`/${servicePath}/ws`]: { target: realtime, changeOrigin: true, ws: true },
      },
    },
  };
});
