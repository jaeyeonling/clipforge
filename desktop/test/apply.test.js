// apply(): 다운로드는 병렬, 설치는 순서대로, 실패하면 나머지를 끊는다.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const C = require("../components");

function tmp() { return fs.mkdtempSync(path.join(os.tmpdir(), "cf-apply-")); }
function zipWith(dir, name, inner) {
  // 7za 로 작은 zip 을 만든다 (components.install 이 7za 로 푼다)
  const src = path.join(dir, "src-" + name); fs.mkdirSync(path.join(src, inner), { recursive: true });
  fs.writeFileSync(path.join(src, inner, "marker.txt"), name);
  const zip = path.join(dir, name + ".zip");
  require("node:child_process").execFileSync(require("7zip-bin").path7za, ["a", "-tzip", "-y", zip, "."], { cwd: src, stdio: "ignore" });
  const buf = fs.readFileSync(zip);
  return { zip, entry: { version: "1", url: require("node:url").pathToFileURL(zip).toString(), sha256: crypto.createHash("sha256").update(buf).digest("hex"), size: buf.length, paths: [inner] } };
}

test("apply: 모든 다운로드가 먼저 시작되고(병렬), 설치는 items 순서대로 끝난다", async () => {
  const dir = tmp(); const runtime = path.join(dir, "runtime"); fs.mkdirSync(runtime);
  const a = zipWith(dir, "alpha", "A"), b = zipWith(dir, "beta", "B"), c = zipWith(dir, "gamma", "Cc");
  const items = [{ name: "alpha", kind: "component", reason: "missing", entry: a.entry }, { name: "beta", kind: "component", reason: "missing", entry: b.entry }, { name: "gamma", kind: "component", reason: "missing", entry: c.entry }];
  const ev = [];
  await C.apply(runtime, items, { downloadDir: path.join(dir, "dl"), onEvent: (e) => ev.push(e), concurrency: 3 });
  const starts = ev.filter((e) => e.type === "start").map((e) => e.name);
  const firstDone = ev.findIndex((e) => e.type === "done");
  const startsBeforeFirstDone = ev.slice(0, firstDone).filter((e) => e.type === "start").length;
  assert.deepStrictEqual(starts, ["alpha", "beta", "gamma"]);
  assert.strictEqual(startsBeforeFirstDone, 3, "첫 설치가 끝나기 전에 세 다운로드가 모두 시작돼야 한다");
  assert.deepStrictEqual(ev.filter((e) => e.type === "done").map((e) => e.name), ["alpha", "beta", "gamma"]);
  for (const [n, inner] of [["alpha", "A"], ["beta", "B"], ["gamma", "Cc"]]) assert.strictEqual(fs.readFileSync(path.join(runtime, inner, "marker.txt"), "utf8"), n);
  assert.ok(!fs.existsSync(a.zip.replace("alpha.zip", path.join("dl", "alpha.zip"))), "받은 zip 은 설치 뒤 지운다");
});

test("apply: 한 항목의 해시가 틀리면 실패하고 나머지는 중단된다", async () => {
  const dir = tmp(); const runtime = path.join(dir, "runtime"); fs.mkdirSync(runtime);
  const a = zipWith(dir, "alpha", "A"), b = zipWith(dir, "beta", "B");
  b.entry.sha256 = "0".repeat(64);
  const items = [{ name: "alpha", kind: "component", reason: "missing", entry: a.entry }, { name: "beta", kind: "component", reason: "missing", entry: b.entry }];
  await assert.rejects(C.apply(runtime, items, { downloadDir: path.join(dir, "dl"), onEvent: () => {} }), /해시 불일치/);
});
