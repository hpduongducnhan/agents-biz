import assert from "node:assert/strict";
import { test } from "node:test";

import { readFileSync } from "node:fs";

import { AuthError, importPublicKey, loadPublicKey, verifyAccess } from "../src/auth.ts";
import { BindingSync, BindingTable } from "../src/bindings.ts";
import { inboundEnvelope, isClientEvent, keysFor, roomFor } from "../src/envelope.ts";
import { TokenBucket } from "../src/ratelimit.ts";
import { makeKeys, makeToken } from "./helpers.ts";

test("verifyAccess accepts a valid token and rejects tampered / expired / wrong typ", async () => {
  const keys = await makeKeys();
  const key = await loadPublicKey(keys.publicKeyPath, "EdDSA");
  const token = await makeToken(keys, { sub: "u1", perms: ["a:b"], sup: true });
  const c = await verifyAccess(token, key, "EdDSA");
  assert.deepEqual([c.sub, c.perms, c.sup], ["u1", ["a:b"], true]);
  assert.ok(c.exp > Date.now() / 1000);
  await assert.rejects(verifyAccess(`${token.slice(0, -4)}AAAA`, key, "EdDSA"), AuthError);
  await assert.rejects(verifyAccess(await makeToken(keys, { sub: "u", ttlSeconds: -5 }), key, "EdDSA"), AuthError);
  await assert.rejects(verifyAccess(await makeToken(keys, { sub: "u", typ: "refresh" }), key, "EdDSA"), AuthError);
  await assert.rejects(verifyAccess("garbage", key, "EdDSA"), AuthError);
});

test("importPublicKey accepts PEM text (key from env)", async () => {
  const keys = await makeKeys();
  const key = await importPublicKey(readFileSync(keys.publicKeyPath, "utf8"), "EdDSA");
  const c = await verifyAccess(await makeToken(keys, { sub: "u9" }), key, "EdDSA");
  assert.equal(c.sub, "u9");
});

test("bindings count sockets per key", () => {
  const t = new BindingTable();
  assert.deepEqual(t.acquire(["user.1", "sup"]), ["user.1", "sup"]);
  assert.deepEqual(t.acquire(["user.1", "sup"]), []); // tab thứ 2 cùng user
  assert.deepEqual(t.acquire(["user.2", "sup"]), ["user.2"]);
  assert.deepEqual(t.release(["user.1", "sup"]), []);
  assert.deepEqual(t.release(["user.1", "sup"]), ["user.1"]);
  assert.deepEqual(t.keys().sort(), ["sup", "user.2"]);
  assert.deepEqual(t.release(["user.2", "sup"]).sort(), ["sup", "user.2"]);
  assert.equal(t.size, 0);
  assert.deepEqual(t.release(["ghost"]), []); // không âm
});

test("token bucket refills over the window", () => {
  const b = new TokenBucket(3, 1000);
  const t0 = 1_000_000;
  assert.deepEqual([b.take(t0), b.take(t0), b.take(t0), b.take(t0)], [true, true, true, false]);
  assert.equal(b.take(t0 + 400), true); // 400ms → hồi 1.2 lượt
  assert.equal(b.take(t0 + 400), false);
  assert.equal(b.take(t0 + 5000), true);
});

test("rooms: user, tenant and sup", () => {
  assert.deepEqual(roomFor("user.42"), { room: "user:42" });
  assert.deepEqual(roomFor("tenant.t1"), { room: "tenant:t1" });
  assert.deepEqual(roomFor("sup"), { room: "sup" });
  assert.deepEqual(roomFor("all"), { all: true });
  assert.equal(roomFor("org.1"), null);
  assert.deepEqual(keysFor({ sub: "u", sup: true }), ["user.u", "sup"]);
  assert.deepEqual(keysFor({ sub: "u", sup: false }), ["user.u"]);
  assert.deepEqual(keysFor({ sub: "u", tid: "t1", sup: true }), ["user.u", "tenant.t1", "sup"]);
});

test("routing keys, rooms and client event names", () => {
  assert.deepEqual(roomFor("user.u1"), { room: "user:u1" });
  assert.equal(roomFor("weird"), null);
  assert.ok(isClientEvent("agent.chat") && isClientEvent("tasks_x.sync_now"));
  assert.ok(!isClientEvent("auth:refresh") && !isClientEvent("Agent.chat") && !isClientEvent("agent") && !isClientEvent("a.b.c"));
  const env = inboundEnvelope("agent.chat", { m: 1 }, { sub: "u", perms: ["x"], sup: false, exp: 1, iat: 0 }, "sid1", "cid1");
  assert.deepEqual(
    { ...env, ts: "t" },
    { v: 1, event: "agent.chat", data: { m: 1 }, claims: { sub: "u", tid: null, perms: ["x"], sup: false }, sid: "sid1", cid: "cid1", ts: "t" },
  );
  const withTenant = inboundEnvelope("agent.chat", {}, { sub: "u", tid: "t1", perms: [], sup: false, exp: 1, iat: 0 }, "s", "c");
  assert.equal(withTenant.claims.tid, "t1");
});

/** RPC giả có thể giữ lại để dựng đúng khe race: mỗi lệnh chờ tới khi test cho qua. */
function fakeRabbit() {
  const calls: string[] = [];
  const waiting: Array<(ok: boolean) => void> = [];
  const apply = (op: "bind" | "unbind", key: string) =>
    new Promise<boolean>((resolveP) => {
      calls.push(`${op} ${key}`);
      waiting.push(resolveP);
    });
  const tick = () => new Promise((r) => setImmediate(r));
  async function settle(ok = true) {
    for (let i = 0; i < 50; i++) {
      await tick();
      const next = waiting.shift();
      if (next) next(ok);
      else if (i > 3) return;
    }
  }
  return { calls, waiting, apply, tick, settle };
}

test("binding sync: a key re-acquired while its unbind is in flight stays bound", async () => {
  const table = new BindingTable();
  const rabbit = fakeRabbit();
  const sync = new BindingSync(() => table.keys(), rabbit.apply);
  table.acquire(["user.a", "sup"]);
  void sync.sync();
  await rabbit.settle();
  assert.deepEqual(sync.keys().sort(), ["sup", "user.a"]);
  table.release(["user.a", "sup"]); // socket A rời: cả 2 key hết người
  void sync.sync();
  await rabbit.tick(); // unbind đầu tiên đang bay
  table.acquire(["user.b", "sup"]); // socket B (cũng superadmin) nối đúng lúc đó
  void sync.sync();
  await rabbit.settle();
  assert.deepEqual(sync.keys().sort(), ["sup", "user.b"]);
});

test("binding sync: reset (new channel) rebinds everything and ignores the old channel's replies", async () => {
  const want = new Set(["user.a"]);
  const rabbit = fakeRabbit();
  const sync = new BindingSync(() => want, rabbit.apply);
  void sync.sync();
  await rabbit.tick(); // bind trên kênh cũ đang bay
  sync.reset(); // nối lại RabbitMQ: queue mới, chưa có binding nào
  want.add("sup"); // socket mới nối trong lúc nối lại
  await rabbit.settle();
  assert.deepEqual(sync.keys().sort(), ["sup", "user.a"]);
  assert.equal(rabbit.calls.filter((c) => c === "bind user.a").length, 2);
});

test("binding sync: a failed RPC stops until the next reset", async () => {
  const want = new Set(["user.a"]);
  const rabbit = fakeRabbit();
  const sync = new BindingSync(() => want, rabbit.apply);
  void sync.sync();
  await rabbit.settle(false);
  assert.deepEqual(sync.keys(), []);
  sync.reset();
  await rabbit.settle(true);
  assert.deepEqual(sync.keys(), ["user.a"]);
});
