// apply(): 다운로드는 병렬, 설치는 순서대로, 실패하면 나머지를 끊는다.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const C = require("../src/components");
const { sevenZip } = require("../scripts/seven-zip");

test.before(async () => {
  process.env.CLIPFORGE_7ZA = (await sevenZip()).exe;
});

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "cf-apply-"));
}
function zipWith(dir, name, inner) {
  // 7za 로 작은 zip 을 만든다 (components.install 이 7za 로 푼다)
  const src = path.join(dir, "src-" + name);
  fs.mkdirSync(path.join(src, inner), { recursive: true });
  fs.writeFileSync(path.join(src, inner, "marker.txt"), name);
  const zip = path.join(dir, name + ".zip");
  require("node:child_process").execFileSync(process.env.CLIPFORGE_7ZA, ["a", "-tzip", "-y", zip, "."], {
    cwd: src,
    stdio: "ignore",
  });
  const buf = fs.readFileSync(zip);
  return {
    zip,
    entry: {
      version: "1",
      url: require("node:url").pathToFileURL(zip).toString(),
      sha256: crypto.createHash("sha256").update(buf).digest("hex"),
      size: buf.length,
      paths: [inner],
    },
  };
}

test("apply: 모든 다운로드가 먼저 시작되고(병렬), 설치는 items 순서대로 끝난다", async () => {
  const dir = tmp();
  const runtime = path.join(dir, "runtime");
  fs.mkdirSync(runtime);
  const a = zipWith(dir, "alpha", "A"),
    b = zipWith(dir, "beta", "B"),
    c = zipWith(dir, "gamma", "Cc");
  const items = [
    { name: "alpha", kind: "component", reason: "missing", entry: a.entry },
    { name: "beta", kind: "component", reason: "missing", entry: b.entry },
    { name: "gamma", kind: "component", reason: "missing", entry: c.entry },
  ];
  const ev = [];
  await C.apply(runtime, items, { downloadDir: path.join(dir, "dl"), onEvent: (e) => ev.push(e), concurrency: 3 });
  const starts = ev.filter((e) => e.type === "start").map((e) => e.name);
  const firstDone = ev.findIndex((e) => e.type === "done");
  const startsBeforeFirstDone = ev.slice(0, firstDone).filter((e) => e.type === "start").length;
  assert.deepStrictEqual(starts, ["alpha", "beta", "gamma"]);
  assert.strictEqual(startsBeforeFirstDone, 3, "첫 설치가 끝나기 전에 세 다운로드가 모두 시작돼야 한다");
  assert.deepStrictEqual(
    ev.filter((e) => e.type === "done").map((e) => e.name),
    ["alpha", "beta", "gamma"],
  );
  for (const [n, inner] of [
    ["alpha", "A"],
    ["beta", "B"],
    ["gamma", "Cc"],
  ])
    assert.strictEqual(fs.readFileSync(path.join(runtime, inner, "marker.txt"), "utf8"), n);
  assert.ok(!fs.existsSync(a.zip.replace("alpha.zip", path.join("dl", "alpha.zip"))), "받은 zip 은 설치 뒤 지운다");
});

test("apply: 한 항목의 해시가 틀리면 실패하고 나머지는 중단된다", async () => {
  const dir = tmp();
  const runtime = path.join(dir, "runtime");
  fs.mkdirSync(runtime);
  const a = zipWith(dir, "alpha", "A"),
    b = zipWith(dir, "beta", "B");
  b.entry.sha256 = "0".repeat(64);
  const items = [
    { name: "alpha", kind: "component", reason: "missing", entry: a.entry },
    { name: "beta", kind: "component", reason: "missing", entry: b.entry },
  ];
  await assert.rejects(C.apply(runtime, items, { downloadDir: path.join(dir, "dl"), onEvent: () => {} }), /손상됐어요/);
});

// GPU 가속처럼 여러 휠(zip)을 받아 site-packages 아래 한 폴더로 합치는 구성요소
function wheelWith(dir, name, sub) {
  const src = path.join(dir, "whl-" + name);
  fs.mkdirSync(path.join(src, "nvidia", sub, "bin"), { recursive: true });
  fs.writeFileSync(path.join(src, "nvidia", sub, "bin", sub + ".dll"), name);
  fs.mkdirSync(path.join(src, name + "-1.0.dist-info"), { recursive: true });
  fs.writeFileSync(path.join(src, name + "-1.0.dist-info", "METADATA"), name);
  const whl = path.join(dir, name + "-1.0-py3-none-win_amd64.whl");
  require("node:child_process").execFileSync(process.env.CLIPFORGE_7ZA, ["a", "-tzip", "-y", whl, "."], {
    cwd: src,
    stdio: "ignore",
  });
  const buf = fs.readFileSync(whl);
  return {
    url: require("node:url").pathToFileURL(whl).toString(),
    sha256: crypto.createHash("sha256").update(buf).digest("hex"),
    size: buf.length,
  };
}

test("apply: 여러 조각(휠)으로 된 구성요소는 차례로 받아 prefix 아래 한 폴더로 설치한다", async () => {
  const dir = tmp();
  const runtime = path.join(dir, "runtime");
  fs.mkdirSync(path.join(runtime, "Lib", "site-packages", "nvidia", "old"), { recursive: true });
  const parts = [wheelWith(dir, "nvidia_cublas", "cublas"), wheelWith(dir, "nvidia_cudnn", "cudnn")];
  const entry = {
    version: "1",
    parts,
    size: parts.reduce((a, p) => a + p.size, 0),
    prefix: "Lib/site-packages",
    paths: ["Lib/site-packages/nvidia"],
  };
  const ev = [];
  const dl = path.join(dir, "dl");
  await C.apply(runtime, [{ name: "cuda", kind: "component", reason: "missing", entry }], {
    downloadDir: dl,
    onEvent: (e) => ev.push(e),
  });
  const nv = path.join(runtime, "Lib", "site-packages", "nvidia");
  assert.strictEqual(fs.readFileSync(path.join(nv, "cublas", "bin", "cublas.dll"), "utf8"), "nvidia_cublas");
  assert.strictEqual(fs.readFileSync(path.join(nv, "cudnn", "bin", "cudnn.dll"), "utf8"), "nvidia_cudnn");
  assert.ok(!fs.existsSync(path.join(nv, "old")), "이전 nvidia 폴더는 통째로 바뀐다");
  assert.ok(C.present(runtime, "cuda"));
  const last = ev.filter((e) => e.type === "download").at(-1);
  assert.strictEqual(last.done, entry.size, "진행률은 조각 합 기준으로 끝까지 간다");
  assert.deepStrictEqual(fs.readdirSync(dl), [], "받은 휠은 설치 뒤 지운다");
  assert.strictEqual(C.savedBytes(dl, entry), 0);
});

test("plan: 받을 곳(url·parts)이 없는 구성요소는 건너뛴다", () => {
  const m = { components: { a: { version: "1" }, b: { version: "1", parts: [{ url: "file:///x.whl", size: 1 }] } } };
  assert.deepStrictEqual(
    C.plan(tmp(), m).map((x) => x.name),
    ["b"],
  );
});
