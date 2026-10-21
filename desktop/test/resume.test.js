// 첫 실행 다운로드가 끊겨도 처음부터 다시 받지 않는다: 끊긴 연결 · 멈춘 응답 · 만료된 링크를 이어 받기로 넘긴다.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const http = require("node:http");
const crypto = require("node:crypto");
const C = require("../components");

const BODY = crypto.randomBytes(256 * 1024);
const entryFor = (url) => ({
  version: "1",
  url,
  size: BODY.length,
  sha256: crypto.createHash("sha256").update(BODY).digest("hex"),
});
const tmpDest = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), "cf-resume-")), "x.zip");

// 요청마다 behave(n, start) 가 어떻게 응답할지 정한다. Range 를 지킨다.
function serve(behave) {
  const log = [];
  const server = http.createServer((req, res) => {
    const m = /bytes=(\d+)-/.exec(req.headers.range || "");
    const start = m ? Number(m[1]) : 0;
    log.push(start);
    const how = behave(log.length, start);
    if (typeof how === "number") {
      res.writeHead(how);
      return res.end();
    }
    res.writeHead(start ? 206 : 200, { "content-length": BODY.length - start });
    const rest = BODY.subarray(start);
    if (how === "drop") {
      res.write(rest.subarray(0, 16 * 1024), () => res.socket.destroy()); // 일부만 보내고 끊는다 (재시도 횟수 × 16KB < 전체)
    } else if (how === "stall") {
      res.write(rest.subarray(0, 32 * 1024)); // 일부만 보내고 멈춘다
    } else res.end(rest);
  });
  return new Promise((resolve) =>
    server.listen(0, "127.0.0.1", () =>
      resolve({ url: `http://127.0.0.1:${server.address().port}/x.zip`, log, server }),
    ),
  );
}

function fastRetry(t) {
  const saved = { ...C.RETRY };
  Object.assign(C.RETRY, { backoffMs: [10], stallMs: 300 });
  t.after(() => Object.assign(C.RETRY, saved));
}

test("연결이 중간에 끊기면 받은 데서부터 이어 받아 끝까지 받는다", async (t) => {
  fastRetry(t);
  const s = await serve((n) => (n === 1 ? "drop" : "ok"));
  t.after(() => s.server.close());
  const retries = [];
  const dest = tmpDest();
  await C.download(entryFor(s.url), dest, (p) => p.retry && retries.push(p));
  assert.deepEqual(fs.readFileSync(dest), BODY);
  assert.equal(s.log[0], 0);
  assert.ok(s.log[1] > 0, "두 번째 요청은 Range 로 이어 받아야 한다");
  assert.equal(retries.length, 1);
});

test("응답이 멈추면 끊고 이어 받는다", async (t) => {
  fastRetry(t);
  const s = await serve((n) => (n === 1 ? "stall" : "ok"));
  t.after(() => s.server.closeAllConnections?.() ?? s.server.close());
  const dest = tmpDest();
  const retries = [];
  await C.download(entryFor(s.url), dest, (p) => p.retry && retries.push(p));
  assert.deepEqual(fs.readFileSync(dest), BODY);
  assert.equal(retries[0].reason, "STALL");
  assert.ok(s.log[1] > 0);
});

test("서버 오류(5xx)·만료된 링크(403)는 다시 시도하고, 없는 파일(404)은 바로 알린다", async (t) => {
  fastRetry(t);
  const s = await serve((n) => (n === 1 ? 503 : n === 2 ? 403 : "ok"));
  t.after(() => s.server.close());
  const dest = tmpDest();
  await C.download(entryFor(s.url), dest);
  assert.deepEqual(fs.readFileSync(dest), BODY);

  const gone = await serve(() => 404);
  t.after(() => gone.server.close());
  await assert.rejects(() => C.download(entryFor(gone.url), tmpDest()), /HTTP 404/);
  assert.equal(gone.log.length, 1);
});

test("계속 끊기면 정해진 횟수까지만 시도하고, 받은 부분은 남겨 다음에 이어 받는다", async (t) => {
  fastRetry(t);
  const s = await serve(() => "drop");
  t.after(() => s.server.close());
  const dest = tmpDest();
  const entry = entryFor(s.url);
  await assert.rejects(() => C.download(entry, dest));
  assert.equal(s.log.length, C.RETRY.attempts);
  const have = C.partialBytes(entry, dest);
  assert.ok(have > 0 && have < BODY.length, "받은 만큼 .part 가 남아 있어야 한다");
});

test("취소하면 기다리지 않고 바로 멈춘다", async (t) => {
  fastRetry(t);
  Object.assign(C.RETRY, { backoffMs: [60000] });
  const s = await serve(() => "drop");
  t.after(() => s.server.close());
  const ac = new AbortController();
  const p = C.download(entryFor(s.url), tmpDest(), (e) => e.retry && ac.abort(), ac.signal);
  await assert.rejects(p, (e) => e.code === "ABORT");
});

test("오류 문구는 할 일을 알려 준다", () => {
  assert.match(C.friendlyError({ code: "ENOTFOUND" }), /인터넷에 연결되지 않아요/);
  assert.match(C.friendlyError({ code: "ENOSPC" }), /디스크 공간/);
  assert.match(C.friendlyError({ code: "ECONNRESET" }), /이어 받아요/);
  assert.equal(C.friendlyError(new Error("기타")), "기타");
});
