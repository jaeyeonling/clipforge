// 서명을 두 번에 나눠 하는 릴리스(release.yml)의 도우미: app-update.yml 쓰기, 서명 뒤 latest.yml 다시 계산.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { appUpdateYml } = require("../scripts/app-update-yml");
const { patchLatestYml, refresh, sha512b64 } = require("../scripts/refresh-latest");

test("app-update.yml: GitHub 피드와, 서명이 있을 때만 게시자 이름(쉼표 있는 CN 도 안전하게)", () => {
  const plain = appUpdateYml({});
  assert.match(plain, /^provider: github$/m);
  assert.match(plain, /^owner: "jaeyeonling"$/m);
  assert.match(plain, /^updaterCacheDirName: "clipforge-desktop-updater"$/m);
  assert.doesNotMatch(plain, /publisherName/);
  const signed = appUpdateYml({ CLIPFORGE_PUBLISHER: "SignPath Foundation; Open Source Developer, Kim" });
  assert.match(signed, /publisherName:\n {2}- "SignPath Foundation"\n {2}- "Open Source Developer, Kim"/);
});

const LATEST = `version: 0.2.0
files:
  - url: clipforge-Setup-0.2.0.exe
    sha512: OLD==
    size: 100
path: clipforge-Setup-0.2.0.exe
sha512: OLD==
releaseDate: '2026-10-21T00:00:00.000Z'
`;

test("latest.yml: 서명으로 바뀐 설치본의 sha512 · size 로 고친다 (다른 파일을 가리키면 거절)", () => {
  const next = patchLatestYml(LATEST, { name: "clipforge-Setup-0.2.0.exe", sha512: "NEW==", size: 123 });
  assert.equal((next.match(/sha512: NEW==/g) || []).length, 2);
  assert.match(next, /^ {4}size: 123$/m);
  assert.match(next, /^releaseDate: /m);
  assert.throws(() => patchLatestYml(LATEST, { name: "other.exe", sha512: "x", size: 1 }), /가리키지 않아요/);
});

test("refresh: 설치본이 바뀌면 --check 는 틀렸다고 하고, 다시 계산하면 맞는다", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cf-latest-"));
  const exe = path.join(dir, "clipforge-Setup-0.2.0.exe");
  fs.writeFileSync(exe, "unsigned");
  fs.writeFileSync(
    path.join(dir, "latest.yml"),
    patchLatestYml(LATEST, { name: "clipforge-Setup-0.2.0.exe", sha512: sha512b64(exe), size: 8 }),
  );
  assert.equal(await refresh(dir, { check: true }), true);
  fs.appendFileSync(exe, "+signature");
  assert.equal(await refresh(dir, { check: true }), false);
  await refresh(dir);
  assert.equal(await refresh(dir, { check: true }), true);
  assert.ok(fs.statSync(`${exe}.blockmap`).size > 0, "blockmap 도 다시 만든다");
});
