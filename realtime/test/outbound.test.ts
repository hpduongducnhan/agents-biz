import assert from "node:assert/strict";
import { after, before, test } from "node:test";

import type { Socket } from "socket.io-client";

import type { RunningRealtime } from "../src/server.ts";
import {
  Publisher,
  type TestKeys,
  connectClient,
  makeKeys,
  makeToken,
  record,
  sleep,
  startTestRealtime,
  waitFor,
} from "./helpers.ts";

let keys: TestKeys;
let rt1: RunningRealtime;
let rt2: RunningRealtime;
let pub: Publisher;
const sockets: Socket[] = [];

async function client(rt: RunningRealtime, claims: Parameters<typeof makeToken>[1]): Promise<Socket> {
  const s = await connectClient(rt, await makeToken(keys, claims));
  sockets.push(s);
  await waitFor(() => rt.bindingKeys().includes(`user.${claims.sub}`));
  return s;
}

before(async () => {
  keys = await makeKeys();
  rt1 = await startTestRealtime(keys);
  rt2 = await startTestRealtime(keys);
  pub = await new Publisher().open();
});

after(async () => {
  for (const s of sockets) s.close();
  await pub.close();
  await rt1.close();
  await rt2.close();
});

test("unauthorized handshake rejected", async () => {
  await assert.rejects(connectClient(rt1, "not-a-token"), /unauthorized/);
  await assert.rejects(connectClient(rt1, await makeToken(keys, { sub: "x", typ: "refresh" })), /unauthorized/);
});

test("message reaches only the target user's socket", async () => {
  const a = await client(rt1, { sub: "t1a" });
  const b = await client(rt2, { sub: "t1b" });
  const gotA = record(a);
  const gotB = record(b);
  pub.out("user.t1a", "fx:hello", { n: 1 }, "cid-1");
  await waitFor(() => gotA.length === 1);
  await sleep(200);
  assert.deepEqual(gotA[0].event, "fx:hello");
  assert.deepEqual(gotA[0].data, { n: 1 });
  assert.equal((gotA[0].meta as { cid: string }).cid, "cid-1");
  assert.equal(gotB.length, 0);
});

test("tenant room: every socket of the tenant on every instance, nobody from another tenant", async () => {
  const a = await client(rt1, { sub: "tn1a", tid: "tenantA" });
  const b = await client(rt2, { sub: "tn1b", tid: "tenantA" });
  const c = await client(rt1, { sub: "tn1c", tid: "tenantB" });
  const gotA = record(a);
  const gotB = record(b);
  const gotC = record(c);
  await waitFor(() => rt1.bindingKeys().includes("tenant.tenantA") && rt2.bindingKeys().includes("tenant.tenantA"));
  pub.out("tenant.tenantA", "data:changed", { keys: ["tasks"] });
  await waitFor(() => gotA.length === 1 && gotB.length === 1);
  await sleep(200);
  assert.deepEqual(gotA[0].data, { keys: ["tasks"] });
  assert.equal(gotC.length, 0);
});

test("sup and all fan out across instances", async () => {
  const a = await client(rt1, { sub: "t2a", sup: true });
  const b = await client(rt2, { sub: "t2b", sup: true });
  const c = await client(rt1, { sub: "t2c" });
  await waitFor(() => rt2.bindingKeys().includes("sup"));
  const [ga, gb, gc] = [record(a), record(b), record(c)];
  pub.out("sup", "core:issue_new", { id: "x" });
  await waitFor(() => ga.length === 1 && gb.length === 1);
  pub.out("all", "sys:hello", { name: "x" });
  await waitFor(() => ga.length === 2 && gb.length === 2 && gc.length === 1);
  assert.deepEqual(gc.map((e) => e.event), ["sys:hello"]);
});

test("sup room only for superusers", async () => {
  const s = await client(rt1, { sub: "t3s", sup: true });
  const u = await client(rt1, { sub: "t3u" });
  await waitFor(() => rt1.bindingKeys().includes("sup"));
  const [gs, gu] = [record(s), record(u)];
  pub.out("sup", "core:quota_request_created", {});
  await waitFor(() => gs.length === 1);
  await sleep(200);
  assert.equal(gu.length, 0);
});

test("last socket leaving unbinds", async () => {
  const one = await client(rt1, { sub: "t4" });
  const two = await client(rt1, { sub: "t4" });
  one.close();
  await sleep(200);
  assert.ok(rt1.bindingKeys().includes("user.t4"));
  two.close();
  await waitFor(() => !rt1.bindingKeys().includes("user.t4"));
});

test("rt:revoke kicks the user on every instance and refuses tokens issued before it", async () => {
  const now = Math.floor(Date.now() / 1000);
  const old = await makeToken(keys, { sub: "t5", iat: now - 10 });
  const one = await connectClient(rt1, old);
  const two = await connectClient(rt2, old);
  sockets.push(one, two);
  const bystander = await client(rt1, { sub: "t5-other" });
  const [got, seen] = [record(one), record(bystander)];
  const closed: string[] = [];
  one.on("disconnect", () => closed.push("one"));
  two.on("disconnect", () => closed.push("two"));
  pub.out("all", "rt:revoke", { sub: "t5", before: now - 5, until: now + 600 });
  await waitFor(() => closed.length === 2);
  await sleep(100);
  assert.deepEqual([got.length, seen.length], [0, 0]); // lệnh cho service realtime, không chuyển tới client
  assert.ok(bystander.connected);
  await assert.rejects(connectClient(rt2, old), /unauthorized/);
  const fresh = await connectClient(rt2, await makeToken(keys, { sub: "t5" })); // đăng nhập lại sau khi mở khoá
  sockets.push(fresh);
});

test("malformed or reserved-name messages are dropped without breaking the bridge", async () => {
  const a = await client(rt1, { sub: "t8" });
  const got = record(a);
  pub.raw("user.t8", "null");
  pub.raw("user.t8", JSON.stringify({ v: 1, event: "disconnect", data: {} }));
  pub.raw("all", JSON.stringify({ v: 1, event: "connect_error", data: {} }));
  pub.raw("user.t8", JSON.stringify({ v: 1, event: "Bad Name", data: {} }));
  pub.out("user.t8", "rt:unknown", {});
  pub.out("user.t8", "fx:ok", { n: 1 });
  await waitFor(() => got.length === 1, 3000);
  await sleep(100);
  assert.deepEqual(got.map((e) => e.event), ["fx:ok"]);
  assert.ok(rt1.rabbitConnected() && a.connected);
});

test("token stream keeps order", async () => {
  const a = await client(rt2, { sub: "t6" });
  const got = record(a);
  for (let seq = 0; seq < 200; seq++) pub.out("user.t6", "agent:token", { run_id: "r", seq });
  await waitFor(() => got.length === 200);
  assert.deepEqual(
    got.map((e) => (e.data as { seq: number }).seq),
    [...Array(200).keys()],
  );
});

test("reconnect restores bindings", async () => {
  const a = await client(rt1, { sub: "t7" });
  const got = record(a);
  await rt1.dropRabbitForTest();
  await waitFor(() => rt1.rabbitConnected() === false || true);
  await waitFor(() => rt1.rabbitConnected(), 8000);
  pub.out("user.t7", "fx:after", { ok: true });
  await waitFor(() => got.length === 1, 5000);
  assert.equal(got[0].event, "fx:after");
});
