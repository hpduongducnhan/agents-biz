import assert from "node:assert/strict";
import { test } from "node:test";

import { loadConfig } from "../src/config.ts";

const base = { RABBITMQ_URL: "amqp://u:p@h:5672/v", AUTH_PUBLIC_KEY_FILE: ".secrets/jwt_public.pem" };

test("defaults and required vars", () => {
  const c = loadConfig(base, "/repo");
  assert.equal(c.rabbitUrl, base.RABBITMQ_URL);
  assert.equal(c.publicKeyPath, "/repo/.secrets/jwt_public.pem");
  assert.equal(c.algorithm, "EdDSA");
  assert.equal(c.port, 8203);
  assert.equal(c.wsPath, "/bizwithagents/ws");
  assert.equal(c.logJson, true);
  assert.equal(c.logLevel, "INFO");
  assert.deepEqual(c.rateLimit, { events: 20, windowMs: 10_000 });
  assert.equal(c.queueMax, 10_000);
  assert.throws(() => loadConfig({ AUTH_PUBLIC_KEY_FILE: "x" }, "/r"), /RABBITMQ_URL/);
  assert.throws(() => loadConfig({ RABBITMQ_URL: "amqp://x" }, "/r"), /AUTH_PUBLIC_KEY_FILE/);
  assert.equal(c.publicKeyPem, "");
});

test("AUTH_PUBLIC_KEY (PEM in env) wins over the file; one-line \\n form restored", () => {
  const pem = "-----BEGIN PUBLIC KEY-----\nAAA\n-----END PUBLIC KEY-----";
  const c = loadConfig({ ...base, AUTH_PUBLIC_KEY: pem.replaceAll("\n", "\\n") }, "/r");
  assert.equal(c.publicKeyPem, pem);
  assert.equal(c.publicKeyPath, "");
  assert.equal(loadConfig({ RABBITMQ_URL: "amqp://x", AUTH_PUBLIC_KEY: pem }, "/r").publicKeyPem, pem);
});

test("AUTH_PUBLIC_KEY escaped twice (\\\\n) or with a stray backslash is restored", () => {
  const pem = "-----BEGIN PUBLIC KEY-----\nAAA\n-----END PUBLIC KEY-----";
  for (const variant of [pem.replaceAll("\n", "\\\\n"), pem.replaceAll("\n", "\\\n")]) {
    assert.equal(loadConfig({ ...base, AUTH_PUBLIC_KEY: variant }, "/r").publicKeyPem, pem);
  }
});

test("WS_PATH falls back to VITE_WS_PATH and strips trailing slash", () => {
  assert.equal(loadConfig({ ...base, VITE_WS_PATH: "/x/ws/" }, "/r").wsPath, "/x/ws");
  assert.equal(loadConfig({ ...base, VITE_WS_PATH: "/x/ws", WS_PATH: "/y" }, "/r").wsPath, "/y");
});

test("values parsed from env (inline comments ignored)", () => {
  const c = loadConfig(
    {
      ...base,
      AUTH_PUBLIC_KEY_FILE: "/abs/pub.pem",
      REALTIME_PORT: "9000   # cổng",
      LOG_JSON: "false",
      LOG_LEVEL: "debug",
      REALTIME_RATE_LIMIT: "5/2s",
      REALTIME_QUEUE_MAX: "50",
    },
    "/r",
  );
  assert.equal(c.publicKeyPath, "/abs/pub.pem");
  assert.equal(c.port, 9000);
  assert.equal(c.logJson, false);
  assert.equal(c.logLevel, "DEBUG");
  assert.deepEqual(c.rateLimit, { events: 5, windowMs: 2000 });
  assert.equal(c.queueMax, 50);
  assert.throws(() => loadConfig({ ...base, REALTIME_RATE_LIMIT: "lots" }, "/r"), /REALTIME_RATE_LIMIT/);
});
