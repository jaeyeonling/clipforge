// components.js 단위 테스트 — node:test (의존성 없음).  실행: npm test  (desktop/)
// 실제 네트워크·7za 없이 돌 수 있는 것: present/plan/download(file:)/sha256/seed. install 은 7za 가 있을 때만(개발 PC 에는 node_modules/7zip-bin).
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
const C = require("../src/components");

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "cf-test-"));
const sha = (buf) => crypto.createHash("sha256").update(buf).digest("hex");
const SEVEN = path.join(__dirname, "..", "node_modules", "7zip-bin", "win", "x64", "7za.exe");

function fakeRuntime(dir, { code = true, python = true, cuda = false, ffmpeg = true, whisper = true } = {}) {
  const touch = (rel) => {
    const p = path.join(dir, rel);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, "x");
  };
  if (code) {
    touch("clipforge/app.py");
    touch("app/dist/index.html");
  }
  if (python) {
    touch("python.exe");
    touch("Lib/site-packages/fastapi/__init__.py");
  }
  if (cuda) touch("Lib/site-packages/nvidia/cublas/bin/cublas64_12.dll");
  if (ffmpeg) touch("bin/ffmpeg.exe");
  if (whisper) touch("models/faster-whisper-large-v3-turbo/model.bin");
}

const manifest = (over = {}) => ({
  engine_code: { version: "0.3.0", url: "file:///C:/x/engine-code-0.3.0.zip", sha256: "a", size: 1 },
  components: {
    "python-base": { version: "p1", url: "file:///C:/x/python-base.zip", sha256: "b", size: 2 },
    cuda: { version: "c1", url: "file:///C:/x/cuda.zip", sha256: "c", size: 3, optional: true },
    ffmpeg: { version: "f1", url: "file:///C:/x/ffmpeg.zip", sha256: "d", size: 4 },
    whisper: { version: "w1", url: "file:///C:/x/whisper.zip", sha256: "e", size: 5 },
  },
  ...over,
});

test("present: 파일 존재로 설치 판정", () => {
  const d = tmp();
  fakeRuntime(d, { cuda: false });
  assert.equal(C.present(d, "engine_code"), true);
  assert.equal(C.present(d, "python-base"), true);
  assert.equal(C.present(d, "cuda"), false);
  assert.equal(C.present(d, "ffmpeg"), true);
  assert.equal(C.present(d, "whisper"), true);
  assert.equal(C.present(path.join(d, "nope"), "ffmpeg"), false);
});

test("plan: 빠진 것은 missing, 버전 다르면 update, optional 은 wantOptional 로 제외", () => {
  const d = tmp();
  fakeRuntime(d, { cuda: false, whisper: false });
  fs.writeFileSync(
    path.join(d, "VERSION.json"),
    JSON.stringify({ engine_version: "0.3.0", component_versions: { "python-base": "p1", ffmpeg: "f0" } }),
  );
  const items = C.plan(d, manifest(), { wantOptional: { cuda: false } });
  const by = Object.fromEntries(items.map((i) => [i.name, i.reason]));
  assert.deepEqual(by, { ffmpeg: "update", whisper: "missing" }); // engine_code·python-base 최신, cuda 제외
  const withCuda = C.plan(d, manifest(), { wantOptional: { cuda: true } });
  assert.ok(withCuda.some((i) => i.name === "cuda" && i.reason === "missing"));
  // url 없는 구성요소(서버에 zip 이 없음)는 계획에 안 들어간다
  const m2 = manifest();
  delete m2.components.whisper.url;
  assert.ok(!C.plan(d, m2, {}).some((i) => i.name === "whisper"));
});

test("download(file:): 복사 + sha256 검증, 불일치면 삭제하고 실패, 같은 파일은 cached", async () => {
  const d = tmp();
  const src = path.join(d, "src.bin");
  const buf = crypto.randomBytes(5000);
  fs.writeFileSync(src, buf);
  const entry = { url: C.fileUrl(src), sha256: sha(buf), size: buf.length };
  const dest = path.join(d, "dl", "src.bin");
  const events = [];
  await C.download(entry, dest, (p) => events.push(p));
  assert.ok(fs.existsSync(dest) && !fs.existsSync(dest + ".part"));
  assert.equal(events.at(-1).done, buf.length);
  const again = [];
  await C.download(entry, dest, (p) => again.push(p));
  assert.equal(again[0].cached, true);
  const bad = { ...entry, sha256: "0".repeat(64) };
  const dest2 = path.join(d, "dl", "bad.bin");
  await assert.rejects(() => C.download(bad, dest2), /손상됐어요/);
  assert.ok(!fs.existsSync(dest2) && !fs.existsSync(dest2 + ".part"));
});

test("seedFromResources: 동봉 코드만 심고 VERSION.json 에 engine_version 기록", async () => {
  const seed = tmp();
  fakeRuntime(seed, { python: false, ffmpeg: false, whisper: false });
  fs.writeFileSync(path.join(seed, "VERSION.json"), JSON.stringify({ engine_version: "0.2.9" }));
  fs.writeFileSync(path.join(seed, "THIRD_PARTY_NOTICES.md"), "n");
  const rt = tmp();
  assert.equal(await C.seedFromResources(rt, seed), true);
  assert.ok(C.present(rt, "engine_code"));
  assert.equal(C.readLocalVersion(rt).engine_version, "0.2.9");
  assert.ok(fs.existsSync(path.join(rt, "THIRD_PARTY_NOTICES.md")));
  assert.equal(await C.seedFromResources(rt, path.join(seed, "missing")), false);
});

test(
  "install: zip 을 풀어 경로 교체, VERSION 갱신, python-base 교체 시 cuda 보존",
  { skip: !fs.existsSync(SEVEN) && "7za 없음" },
  async () => {
    const d = tmp();
    fakeRuntime(d, { cuda: true });
    fs.writeFileSync(path.join(d, "bin", "old.txt"), "old");
    // ffmpeg zip: bin/ffmpeg.exe (new) + bin/new.txt
    const stage = tmp();
    fs.mkdirSync(path.join(stage, "bin"));
    fs.writeFileSync(path.join(stage, "bin", "ffmpeg.exe"), "NEW");
    fs.writeFileSync(path.join(stage, "bin", "new.txt"), "n");
    const zip = path.join(tmp(), "ffmpeg-9.zip");
    execFileSync(SEVEN, ["a", "-tzip", "-bd", zip, "bin"], { cwd: stage, stdio: "ignore" });
    const phases = [];
    await C.install(d, { name: "ffmpeg", kind: "component", reason: "update", entry: { version: "9.9" } }, zip, (p) =>
      phases.push(p.phase),
    );
    assert.equal(fs.readFileSync(path.join(d, "bin", "ffmpeg.exe"), "utf8"), "NEW");
    assert.ok(!fs.existsSync(path.join(d, "bin", "old.txt")), "옛 폴더는 통째로 교체");
    assert.ok(fs.existsSync(path.join(d, "bin", "new.txt")));
    assert.ok(phases.includes("extract") && phases.includes("swap"));
    assert.equal(C.readLocalVersion(d).component_versions.ffmpeg, "9.9");
    assert.ok(!fs.existsSync(path.join(d, "_staging")) && !fs.existsSync(path.join(d, "_prev")));
    // python-base 교체: Lib 가 통째로 바뀌어도 Lib/site-packages/nvidia(cuda) 는 살아남는다
    const st2 = tmp();
    fs.mkdirSync(path.join(st2, "Lib", "site-packages", "fastapi"), { recursive: true });
    fs.writeFileSync(path.join(st2, "Lib", "site-packages", "fastapi", "__init__.py"), "v2");
    fs.writeFileSync(path.join(st2, "python.exe"), "py2");
    const zip2 = path.join(tmp(), "python-base.zip");
    execFileSync(SEVEN, ["a", "-tzip", "-bd", zip2, "python.exe", "Lib"], { cwd: st2, stdio: "ignore" });
    await C.install(
      d,
      { name: "python-base", kind: "component", reason: "update", entry: { version: "p2" } },
      zip2,
      () => {},
    );
    assert.equal(fs.readFileSync(path.join(d, "python.exe"), "utf8"), "py2");
    assert.equal(fs.readFileSync(path.join(d, "Lib", "site-packages", "fastapi", "__init__.py"), "utf8"), "v2");
    assert.ok(C.present(d, "cuda"), "cuda 폴더 보존");
    assert.equal(C.readLocalVersion(d).component_versions["python-base"], "p2");
    // engine_code 교체
    const st3 = tmp();
    fs.mkdirSync(path.join(st3, "clipforge"));
    fs.writeFileSync(path.join(st3, "clipforge", "app.py"), "code2");
    fs.mkdirSync(path.join(st3, "app", "dist"), { recursive: true });
    fs.writeFileSync(path.join(st3, "app", "dist", "index.html"), "ui2");
    const zip3 = path.join(tmp(), "engine-code.zip");
    execFileSync(SEVEN, ["a", "-tzip", "-bd", zip3, "clipforge", "app"], { cwd: st3, stdio: "ignore" });
    await C.install(
      d,
      { name: "engine_code", kind: "engine_code", reason: "update", entry: { version: "0.9.0" } },
      zip3,
      () => {},
    );
    assert.equal(fs.readFileSync(path.join(d, "clipforge", "app.py"), "utf8"), "code2");
    assert.equal(C.readLocalVersion(d).engine_version, "0.9.0");
  },
);

test(
  "install: 손상된 zip 이면 실패하고 기존 파일은 그대로",
  { skip: !fs.existsSync(SEVEN) && "7za 없음" },
  async () => {
    const d = tmp();
    fakeRuntime(d);
    const bad = path.join(tmp(), "ffmpeg-bad.zip");
    fs.writeFileSync(bad, "not a zip");
    await assert.rejects(
      () =>
        C.install(d, { name: "ffmpeg", kind: "component", reason: "update", entry: { version: "x" } }, bad, () => {}),
      /7za exit/,
    );
    assert.equal(fs.readFileSync(path.join(d, "bin", "ffmpeg.exe"), "utf8"), "x", "교체 전 실패 → 원본 유지");
    assert.ok(!C.readLocalVersion(d), "VERSION 은 안 바뀜");
  },
);
