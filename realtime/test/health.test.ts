import assert from "node:assert/strict";
import { after, before, test } from "node:test";

import type { RunningRealtime } from "../src/server.ts";
import { Publisher, type TestKeys, WS_PATH, connectClient, makeKeys, makeToken, record, startTestRealtime, waitFor } from "./helpers.ts";

let keys: TestKeys;
let rt: RunningRealtime;
let pub: Publisher;

before(async () => {
  keys = await makeKeys();
  rt = await startTestRealtime(keys);
  pub = await new Publisher().open();
});

after(async () => {
  await pub.close();
  await rt.close();
});

async function get(path: string) {
  const r = await fetch(`http://127.0.0.1:${rt.port}${WS_PATH}${path}`);
  return { status: r.status, body: await r.json() };
}

test("health and metrics report state", async () => {
  const h = await get("/health");
  assert.equal(h.status, 200);
  assert.deepEqual(h.body, { status: "ok", rabbit: true, sockets: 0 });
  const s = await connectClient(rt, await makeToken(keys, { sub: "h1" }));
  await waitFor(() => rt.bindingKeys().includes("user.h1"));
  const got = record(s);
  pub.out("user.h1", "fx:ping", {});
  await waitFor(() => got.length === 1);
  const m = await get("/metrics");
  assert.equal(m.status, 200);
  assert.equal(m.body.sockets, 1);
  assert.ok(m.body.delivered >= 1 && m.body.bindings >= 1);
  s.close();
  await rt.dropRabbitForTest();
  const degraded = await get("/health");
  assert.equal(degraded.status, 503);
  assert.equal(degraded.body.status, "degraded");
  await waitFor(() => rt.rabbitConnected(), 8000);
  assert.equal((await get("/nope")).status, 404);
});
