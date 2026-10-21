// 껍데기 보안 규칙: 화면이 열 수 있는 경로, 앱 화면 주소.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { isSafeToOpen } = require("../src/ipc");
const { pageFile } = require("../src/window");

test("경로 열기: 폴더와 결과물만 열고, 실행 파일 · 상대 경로 · 없는 파일은 열지 않는다", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cf-open-"));
  const touch = (n) => (fs.writeFileSync(path.join(dir, n), "x"), path.join(dir, n));
  assert.equal(isSafeToOpen(dir), true);
  for (const ok of ["a.mp4", "b.xml", "c.srt", "d.vegas.txt", "e.zip"]) assert.equal(isSafeToOpen(touch(ok)), true, ok);
  for (const bad of ["x.exe", "y.bat", "z.ps1", "w.lnk", "v.cmd", "u.html"])
    assert.equal(isSafeToOpen(touch(bad)), false, bad);
  assert.equal(isSafeToOpen("relative/a.mp4"), false);
  assert.equal(isSafeToOpen(path.join(dir, "missing.mp4")), false);
  assert.equal(isSafeToOpen(""), false);
  assert.equal(isSafeToOpen({ path: dir }), false);
});

test("앱 화면 주소: pages/ 아래만 내주고 ../ 로 빠져나가지 못한다", () => {
  assert.ok(pageFile("clipforge://app/setup.html").endsWith(path.join("pages", "setup.html")));
  assert.equal(pageFile("clipforge://app/..%5Cmain.js"), null, "인코딩된 역슬래시로 폴더 밖");
  assert.equal(pageFile("clipforge://app/..%5C..%5Cpackage.json"), null);
  assert.equal(pageFile("clipforge://app/%E0%A4%A"), null, "깨진 인코딩");
  assert.equal(pageFile("clipforge://app/missing.html"), null, "없는 파일");
  assert.equal(pageFile("clipforge://other/setup.html"), null);
});
