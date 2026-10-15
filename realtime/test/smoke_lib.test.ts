import assert from "node:assert/strict";
import { test } from "node:test";

import {
  assetPaths,
  cacheProblems,
  classifyConnectError,
  containsText,
  decodeJwt,
  fakeIp,
  isDevServer,
  mongoMode,
  parseOptions,
  rateLimitEnabled,
  sessionFrom,
  tokenFrom,
  versionProblem,
} from "../scripts/smoke_lib.ts";

const jwt = (claims: object): string => `h.${Buffer.from(JSON.stringify(claims)).toString("base64url")}.s`;

test("parseOptions: profile ghi dữ liệu chỉ chạy với máy local", () => {
  for (const profile of ["local", "docker"]) {
    assert.throws(
      () => parseOptions(["https://bizwithagents.example.com", "--profile", profile], { SMOKE_EXPECT_MONGO: "on" }),
      /chỉ chạy với máy local/,
    );
  }
  const o = parseOptions(["http://127.0.0.1:8204/", "--profile", "docker"], { SMOKE_EXPECT_MONGO: "off", SMOKE_RUN_ID: "abcd12" });
  assert.equal(o.base, "http://127.0.0.1:8204");
  assert.deepEqual(o.admin, { email: "root@smoke.test", password: "smoke-password-1" });
  assert.equal(o.expectMongo, "off");
  assert.equal(o.runId, "abcd12");
  assert.equal(parseOptions(["http://[::1]:8201", "--profile", "local"], { SMOKE_EXPECT_MONGO: "on" }).profile, "local");
});

test("parseOptions: SMOKE_EXPECT_MONGO bắt buộc với local / docker; prod mặc định on", () => {
  assert.throws(() => parseOptions(["http://127.0.0.1:8201", "--profile", "local"], {}), /SMOKE_EXPECT_MONGO/);
  assert.throws(
    () => parseOptions(["http://127.0.0.1:8201", "--profile", "local"], { SMOKE_EXPECT_MONGO: "yes" }),
    /SMOKE_EXPECT_MONGO/,
  );
  assert.equal(parseOptions(["https://x.example", "--profile", "prod"], {}).expectMongo, "on");
});

test("parseOptions: tài khoản theo profile + lỗi tham số", () => {
  const local = parseOptions(["http://localhost:8201", "--profile", "local"], { SMOKE_EXPECT_MONGO: "on", SEED_PASSWORD: "pw-seed" });
  assert.deepEqual(local.admin, { email: "superadmin@test.local", password: "pw-seed" });
  assert.equal(local.prodLogin, null);
  const prod = parseOptions(["https://x.example", "--profile", "prod"], {
    SMOKE_EMAIL: "s@x.vn",
    SMOKE_PASSWORD: "p",
    SMOKE_EXPECT_VERSION: "abc",
  });
  assert.equal(prod.admin, null);
  assert.deepEqual(prod.prodLogin, { email: "s@x.vn", password: "p" });
  assert.equal(prod.expectVersion, "abc");
  assert.match(prod.runId, /^[0-9a-f]{6}$/);
  assert.throws(() => parseOptions(["https://x.example", "--profile", "prod"], { SMOKE_EMAIL: "s@x.vn" }), /cùng nhau/);
  assert.throws(() => parseOptions(["x", "--profile", "prod"], {}), /URL gốc/);
  assert.throws(() => parseOptions(["https://x.example", "--profile", "staging"], {}), /--profile/);
});

test("rate limit: prod chỉ chạy khi SMOKE_RATE_LIMIT=1; IP giả khác nhau theo slot và theo lượt", () => {
  assert.equal(rateLimitEnabled({ profile: "local", rateLimitOnProd: false }), true);
  assert.equal(rateLimitEnabled({ profile: "prod", rateLimitOnProd: false }), false);
  assert.equal(rateLimitEnabled({ profile: "prod", rateLimitOnProd: true }), true);
  assert.equal(parseOptions(["https://x.example", "--profile", "prod"], { SMOKE_RATE_LIMIT: "1" }).rateLimitOnProd, true);
  const ips = [0, 1, 2, 3].map((slot) => fakeIp("ab12cd", slot));
  assert.equal(new Set(ips).size, 4);
  for (const ip of ips) assert.match(ip, /^203\.0\.113\.\d{1,3}$/);
  assert.notEqual(fakeIp("ab12cd", 0), fakeIp("ff00aa", 0));
  assert.equal(fakeIp("zz", 0), "203.0.113.1");
});

test("sessionFrom: đọc token (có hoặc không bọc tokens) + claim sub / sup / perms", () => {
  const access = jwt({ sub: "u1", sup: false, perms: ["user.view"] });
  assert.deepEqual(sessionFrom({ user: { id: "u1" }, tokens: { access_token: access, refresh_token: "r1" } }), {
    access,
    refresh: "r1",
    sub: "u1",
    sup: false,
    perms: ["user.view"],
  });
  const sa = sessionFrom({ access_token: jwt({ sub: "s", sup: true }), refresh_token: "r2" });
  assert.equal(sa.sup, true);
  assert.deepEqual(sa.perms, []);
  assert.throws(() => sessionFrom({ user: {} }), /access_token/);
  assert.throws(() => sessionFrom(null), /access_token/);
  assert.throws(() => decodeJwt("khong-phai-jwt"), /JWT/);
});

test("assetPaths + isDevServer", () => {
  const html =
    '<script type="module" crossorigin src="/assets/index-AbC1.js"></script>' +
    '<link rel="stylesheet" href="/assets/index-x9.css"><link rel="modulepreload" href="/assets/index-AbC1.js">';
  assert.deepEqual(assetPaths(html), ["/assets/index-AbC1.js", "/assets/index-x9.css"]);
  assert.equal(isDevServer(html), false);
  assert.equal(isDevServer('<script type="module" src="/@vite/client"></script>'), true);
});

test("cacheProblems: index no-cache, không HIT ở Cloudflare, asset 200 + immutable", () => {
  const good = { path: "/assets/a.js", status: 200, cacheControl: "public, max-age=31536000, immutable" };
  assert.deepEqual(cacheProblems({ cacheControl: "no-cache", cfCacheStatus: "DYNAMIC" }, [good]), []);
  assert.deepEqual(cacheProblems({ cacheControl: "no-cache", cfCacheStatus: null }, [good]), []);
  const bad = cacheProblems({ cacheControl: "max-age=3600", cfCacheStatus: "HIT" }, [
    { ...good, status: 404 },
    { ...good, path: "/assets/b.css", cacheControl: "max-age=60" },
  ]);
  assert.equal(bad.length, 4);
  assert.match(bad.join("\n"), /no-cache[\s\S]*HIT[\s\S]*404[\s\S]*immutable/);
  assert.deepEqual(cacheProblems({ cacheControl: "no-cache", cfCacheStatus: null }, []), [
    "index.html không trỏ tới asset /assets/*.js|css nào",
  ]);
});

test("mongoMode + classifyConnectError + versionProblem + containsText", () => {
  assert.equal(mongoMode({ "postgres.rw": "ok", mongo: "disabled", rabbitmq: "ok" }), "off");
  assert.equal(mongoMode({ "mongo.rw": "ok", "mongo.ro": "ok" }), "on");
  assert.throws(() => mongoMode({ "postgres.rw": "ok" }), /chế độ Mongo/);
  assert.equal(classifyConnectError("unauthorized"), "auth");
  assert.equal(classifyConnectError("websocket error"), "transport");
  assert.equal(classifyConnectError("timeout"), "transport");
  const sha = "0123456789abcdef0123456789abcdef01234567";
  assert.equal(versionProblem("bất kỳ", null), null);
  assert.equal(versionProblem(sha, sha), null);
  assert.equal(versionProblem(sha.slice(0, 7), sha), null);
  assert.match(versionProblem("dev", sha) ?? "", /SOURCE_COMMIT/);
  assert.match(versionProblem(undefined, sha) ?? "", /SOURCE_COMMIT/);
  assert.match(versionProblem("fffffff", sha) ?? "", /mong đợi/);
  assert.equal(containsText({ a: [{ title: "Smoke x1" }] }, "Smoke x1"), true);
  assert.equal(containsText(null, "x"), false);
});

test("tokenFrom: lấy token thô trong link mời / đặt lại mật khẩu của thư, không có → null", () => {
  assert.equal(tokenFrom("Mở http://app/invite/Ab-9_x.\nHết hạn sau 7 ngày", "/invite/"), "Ab-9_x");
  assert.equal(tokenFrom("http://app/reset-password?token=Zz_1-2&x=1", "token="), "Zz_1-2");
  assert.equal(tokenFrom("không có link", "token="), null);
  assert.equal(tokenFrom("http://app/invite/", "/invite/"), null);
});
