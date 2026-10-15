import assert from "node:assert/strict";
import { test } from "node:test";
import { Writable } from "node:stream";

import { createLogger } from "../src/log.ts";

function sink() {
  const lines: string[] = [];
  const stream = new Writable({
    write(chunk, _enc, cb) {
      lines.push(...chunk.toString().split("\n").filter(Boolean));
      cb();
    },
  });
  return { lines, stream };
}

test("JSON line has the same keys as the backend", () => {
  const { lines, stream } = sink();
  const log = createLogger({ json: true, level: "INFO", stream });
  log.info("xin chào", { loc: "ws2001", cid: "c1", sockets: 3 });
  const rec = JSON.parse(lines[0]);
  assert.deepEqual(Object.keys(rec).slice(0, 8), ["ts", "level", "logger", "proc", "module", "loc", "cid", "msg"]);
  assert.equal(rec.logger, "bw");
  assert.equal(rec.proc, "realtime");
  assert.equal(rec.module, "core");
  assert.equal(rec.loc, "ws2001");
  assert.equal(rec.cid, "c1");
  assert.equal(rec.sockets, 3);
  assert.match(rec.ts, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/);
  log.warn("thiếu");
  const bare = JSON.parse(lines[1]);
  assert.equal(bare.loc, "-");
  assert.equal(bare.cid, "-");
  assert.equal(bare.level, "WARNING");
});

test("text line shape", () => {
  const { lines, stream } = sink();
  createLogger({ json: false, level: "INFO", stream }).info("kết nối", { loc: "ws2101", cid: "c9", broker: "main" });
  assert.match(lines[0], /^\d\d:\d\d:\d\d\.\d{3} INFO    realtime cid=c9 \[ws2101\] kết nối broker=main$/);
});

test("level filtering", () => {
  const { lines, stream } = sink();
  const log = createLogger({ json: true, level: "WARNING", stream });
  log.debug("a");
  log.info("b");
  log.warn("c");
  log.error("d");
  assert.deepEqual(lines.map((l) => JSON.parse(l).msg), ["c", "d"]);
});

test("token-like fields are redacted", () => {
  const { lines, stream } = sink();
  createLogger({ json: true, level: "INFO", stream }).info("x", { token: "abc", authorization: "Bearer z", ok: 1 });
  const rec = JSON.parse(lines[0]);
  assert.equal(rec.token, "[REDACTED]");
  assert.equal(rec.authorization, "[REDACTED]");
  assert.equal(rec.ok, 1);
});
