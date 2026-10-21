// 패키징 회귀 방지: 설치본에 들어가는 파일만으로 껍데기가 뜰 수 있어야 한다.
// (release.config.js 가 빠져 설치본이 시작하자마자 "Cannot find module" 로 죽은 적이 있다 — 2026-10-20)
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
// 파일 목록만 본다. 엔진 번들(engine-dist/)이 없는 CI 에서도 설정을 불러올 수 있게 엔진 검사를 끈다.
process.env.CLIPFORGE_SKIP_ENGINE = "1";
const cfg = require(path.join(ROOT, "electron-builder.config.js"));
const pkg = require(path.join(ROOT, "package.json"));

/** electron-builder files 패턴(정확한 이름 또는 "폴더/**")에 걸리는가 */
function packaged(rel) {
  return cfg.files.some((f) => (f.endsWith("/**") ? rel.startsWith(f.slice(0, -2)) : rel === f));
}

function localRequires(rel) {
  const src = fs.readFileSync(path.join(ROOT, rel), "utf8");
  const out = [];
  for (const m of src.matchAll(/require\(\s*["'](\.{1,2}\/[\w./-]+?)(?:\.js)?["']\s*\)/g))
    out.push(path.posix.normalize(path.posix.join(path.posix.dirname(rel), m[1] + ".js")));
  return out;
}

test("진입점과 preload 가 require 하는 로컬 모듈이 전부 설치본에 들어간다", () => {
  assert.equal(pkg.main, "src/main.js");
  const seen = new Set();
  const queue = ["src/main.js", "src/preload.js"];
  while (queue.length) {
    const f = queue.pop();
    if (seen.has(f)) continue;
    seen.add(f);
    assert.ok(packaged(f), `${f} 가 electron-builder files 에 없음`);
    assert.ok(fs.existsSync(path.join(ROOT, f)), `${f} 파일이 없음`);
    queue.push(...localRequires(f));
  }
  for (const m of ["release.config", "window", "firstrun", "updates", "components"])
    assert.ok(seen.has(`src/${m}.js`), `src/${m}.js 가 의존성으로 잡혀야 함`);
});

test("앱 화면(부팅 · 설치)이 쓰는 파일이 전부 있고 설치본에 들어가며 CSP 가 걸려 있다", () => {
  for (const page of ["boot.html", "setup.html"]) {
    const rel = `src/pages/${page}`;
    assert.ok(packaged(rel) && fs.existsSync(path.join(ROOT, rel)), rel);
    const html = fs.readFileSync(path.join(ROOT, rel), "utf8");
    assert.match(html, /Content-Security-Policy/, `${page} 에 CSP 가 있어야 함`);
    assert.doesNotMatch(html, /<script>|onclick=|style="/, `${page} 에 인라인 스크립트 · 스타일이 없어야 함`);
    for (const m of html.matchAll(/(?:src|href)="([^"]+)"/g))
      assert.ok(fs.existsSync(path.join(ROOT, "src/pages", m[1])), `${page} → ${m[1]} 파일이 없음`);
  }
  assert.ok(packaged("assets/icon.png") && packaged("assets/tray.png"));
});
