/** Entry service `realtime`: đọc cấu hình (.env gốc repo nạp qua --env-file-if-exists), chạy tới SIGINT / SIGTERM. */

import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { loadConfig } from "./config.ts";
import { startRealtime } from "./server.ts";
import { createLogger } from "./log.ts";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const config = loadConfig(process.env, root);
const log = createLogger({ json: config.logJson, level: config.logLevel });

process.on("unhandledRejection", (reason) => {
  log.error(`promise bị từ chối không ai bắt: ${String(reason)}`, { loc: "ws2505" });
});

const server = await startRealtime(config, log);

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, async () => {
    await server.close();
    process.exit(0);
  });
}
