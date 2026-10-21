// 패키징 회귀 방지: main.js 가 require 하는 로컬 모듈이 electron-builder 의 files 목록에 전부 있어야 한다.
// (release.config.js 가 빠져 설치본이 시작하자마자 "Cannot find module" 로 죽은 적이 있다 — 2026-10-20)
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
// 파일 목록만 본다. 엔진 번들(engine-dist/)이 없는 CI 에서도 설정을 불러올 수 있게 엔진 검사를 끈다.
process.env.CLIPFORGE_SKIP_ENGINE = "1";
const cfg = require(path.join(ROOT, "electron-builder.config.js"));

function localRequires(file) {
  const src = fs.readFileSync(path.join(ROOT, file), "utf8");
  const out = new Set();
  for (const m of src.matchAll(/require\(\s*["']\.\/([\w.-]+?)(?:\.js)?["']\s*\)/g)) out.add(`${m[1]}.js`);
  return [...out];
}

test("electron-builder files 에 main/preload 가 require 하는 로컬 모듈이 전부 들어 있다", () => {
  const files = new Set(cfg.files);
  const seen = new Set();
  const queue = ["main.js", "preload.js"];
  while (queue.length) {
    const f = queue.pop();
    if (seen.has(f)) continue;
    seen.add(f);
    assert.ok(files.has(f), `${f} 가 electron-builder files 에 없음`);
    assert.ok(fs.existsSync(path.join(ROOT, f)), `${f} 파일이 없음`);
    for (const dep of localRequires(f)) queue.push(dep);
  }
  assert.ok(seen.has("release.config.js"), "release.config.js 가 main.js 의존성으로 잡혀야 함");
});
