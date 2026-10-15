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
let rt: RunningRealtime;
let limited: RunningRealtime;
let graced: RunningRealtime;
let pub: Publisher;
const sockets: Socket[] = [];

type Ack = { accepted?: boolean; error?: string; cid?: string; ok?: boolean };

function send(s: Socket, event: string, data?: unknown): Promise<Ack> {
  return new Promise((resolveP, reject) =>
    s.timeout(3000).emit(event, data, (err: Error | null, ack: Ack) => (err ? reject(err) : resolveP(ack))),
  );
}

async function client(g: RunningRealtime, claims: Parameters<typeof makeToken>[1]): Promise<Socket> {
  const s = await connectClient(g, await makeToken(keys, claims));
  sockets.push(s);
  await waitFor(() => g.bindingKeys().includes(`user.${claims.sub}`));
  return s;
}

/** Queue riêng nghe bw.rt.in theo routing key — như consumer của module phía Python. */
async function listenIn(routingKey: string) {
  const q = await pub.ch.assertQueue("", { exclusive: true, autoDelete: true });
  await pub.ch.bindQueue(q.queue, "bw.rt.in", routingKey);
  const got: Array<{ env: Record<string, unknown>; correlationId: string }> = [];
  await pub.ch.consume(q.queue, (m) => m && got.push({ env: JSON.parse(m.content.toString()), correlationId: m.properties.correlationId }), { noAck: true });
  return got;
}

before(async () => {
  keys = await makeKeys();
  rt = await startTestRealtime(keys);
  limited = await startTestRealtime(keys, { REALTIME_RATE_LIMIT: "3/10s" });
  graced = await startTestRealtime(keys, {}, { expiryGraceMs: 300 });
  pub = await new Publisher().open();
});

after(async () => {
  for (const s of sockets) s.close();
  await pub.close();
  await rt.close();
  await limited.close();
  await graced.close();
});

test("client event published with claims and cid", async () => {
  const got = await listenIn("fxin.ping");
  const s = await client(rt, { sub: "i1", tid: "tenantX", perms: ["fxin:read"] });
  const ack = await send(s, "fxin.ping", { text: "hi" });
  assert.equal(ack.accepted, true);
  assert.match(ack.cid ?? "", /^[0-9a-f]{32}$/);
  await waitFor(() => got.length === 1);
  const { env, correlationId } = got[0];
  assert.equal(correlationId, ack.cid);
  assert.deepEqual(
    { v: env.v, event: env.event, data: env.data, claims: env.claims, sid: env.sid, cid: env.cid },
    {
      v: 1,
      event: "fxin.ping",
      data: { text: "hi" },
      claims: { sub: "i1", tid: "tenantX", perms: ["fxin:read"], sup: false },
      sid: s.id,
      cid: ack.cid,
    },
  );
});

test("rate limit and invalid names are rejected", async () => {
  const got = await listenIn("fxin.burst");
  const s = await client(limited, { sub: "i2" });
  const acks = [];
  for (let i = 0; i < 4; i++) acks.push(await send(s, "fxin.burst", { i }));
  assert.deepEqual(acks.map((a) => a.accepted), [true, true, true, false]);
  assert.equal(acks[3].error, "rate_limited");
  const bad = await send(await client(rt, { sub: "i2b" }), "Bad.Name", {});
  assert.deepEqual(bad, { accepted: false, error: "invalid_event" });
  await sleep(300);
  assert.equal(got.length, 3);
});

test("expired token blocks events until refresh", async () => {
  const s = await client(rt, { sub: "i3", ttlSeconds: 2 });
  const got = record(s);
  await waitFor(() => got.some((e) => e.event === "auth:expired"), 5000);
  const blocked = await send(s, "fxin.ping", {});
  assert.deepEqual(blocked, { accepted: false, error: "token_expired" });
  const refreshed = await send(s, "auth:refresh", { token: await makeToken(keys, { sub: "i3" }) });
  assert.deepEqual(refreshed, { ok: true });
  assert.equal((await send(s, "fxin.ping", {})).accepted, true);
});

test("expired socket that does not refresh is disconnected after the grace period", async () => {
  const s = await client(graced, { sub: "i3g", ttlSeconds: 2 });
  const reason = new Promise<string>((r) => s.once("disconnect", r));
  assert.equal(await reason, "io server disconnect");
  await waitFor(() => !graced.bindingKeys().includes("user.i3g"));
});

test("refresh within the grace period keeps the socket", async () => {
  const s = await client(graced, { sub: "i3r", ttlSeconds: 2 });
  const got = record(s);
  await waitFor(() => got.some((e) => e.event === "auth:expired"), 5000);
  assert.deepEqual(await send(s, "auth:refresh", { token: await makeToken(keys, { sub: "i3r" }) }), { ok: true });
  await sleep(600);
  assert.ok(s.connected);
});

test("refresh racing a disconnect neither leaks nor double-releases bindings", async () => {
  const keep = await client(rt, { sub: "i6keep", sup: true });
  const got = record(keep);
  const perms = Array.from({ length: 20_000 }, (_, i) => `perm_${i}:read`); // token lớn → kiểm chữ ký mất vài ms
  for (let i = 0; i < 5; i++) {
    const s = await client(rt, { sub: `i6-${i}` });
    const token = await makeToken(keys, { sub: `i6-${i}`, sup: true, perms });
    s.emit("auth:refresh", { token }, () => {});
    await new Promise((r) => setTimeout(r, 1)); // socket rời khi server đang kiểm token
    s.disconnect();
  }
  await sleep(300);
  assert.ok(rt.bindingKeys().filter((k) => k.startsWith("user.i6-")).length === 0);
  pub.out("sup", "fx:still", {});
  await waitFor(() => got.length === 1);
});

test("channel closed by RabbitMQ: bridge reconnects instead of going silent", async () => {
  const s = await client(rt, { sub: "i7" });
  const got = record(s);
  await pub.ch.deleteExchange("bw.rt.in");
  await send(s, "fxin.lost", {}); // publish vào exchange đã mất → RabbitMQ đóng kênh, kết nối vẫn sống
  await waitFor(() => !rt.rabbitConnected(), 3000);
  await waitFor(() => rt.rabbitConnected(), 8000); // nối lại: exchange được khai lại
  // Khai lại y hệt backend (`names.rt_*_exchange()`) — khác tham số thì RabbitMQ đóng kênh (PRECONDITION_FAILED).
  await pub.ch.assertExchange("bw.rt.out", "topic", { durable: true });
  await pub.ch.assertExchange("bw.rt.in", "topic", { durable: true, arguments: { "alternate-exchange": "bw.rt.in.unrouted" } });
  await pub.ch.assertExchange("bw.rt.in.unrouted", "fanout", { durable: true });
  const heard = await listenIn("fxin.back");
  assert.equal((await send(s, "fxin.back", {})).accepted, true);
  await waitFor(() => heard.length === 1);
  pub.out("user.i7", "fx:back", {});
  await waitFor(() => got.some((e) => e.event === "fx:back"));
});

test("refresh to a superadmin token joins the sup room", async () => {
  const s = await client(rt, { sub: "i4" });
  const got = record(s);
  assert.deepEqual(await send(s, "auth:refresh", { token: await makeToken(keys, { sub: "i4", sup: true }) }), { ok: true });
  await waitFor(() => rt.bindingKeys().includes("sup"));
  pub.out("sup", "fx:new", {});
  await waitFor(() => got.some((e) => e.event === "fx:new"));
});

test("refresh with another user's token is rejected", async () => {
  const s = await client(rt, { sub: "i5" });
  const got = record(s);
  const bad = await send(s, "auth:refresh", { token: await makeToken(keys, { sub: "someone-else" }) });
  assert.deepEqual(bad, { ok: false, error: "user_mismatch" });
  const garbage = await send(s, "auth:refresh", { token: "nope" });
  assert.deepEqual(garbage, { ok: false, error: "unauthorized" });
  pub.out("user.i5", "fx:still", {});
  await waitFor(() => got.length === 1);
});
