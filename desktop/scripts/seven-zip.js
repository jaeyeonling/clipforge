// 7-Zip: electron-builder 가 체크섬을 확인해 받아 두는 최신 7za 를 쓴다 — 설치본(afterPack) · 개발 · 테스트 모두 같은 것.
// (예전 7zip-bin 패키지의 7za 는 2021년 버전이라 쓰지 않는다)
"use strict";
const path = require("node:path");

/** { exe: 7za.exe 경로, license: 라이선스 원문 경로 } — 처음 부를 때 한 번 내려받는다 */
async function sevenZip() {
  const { getPath7za } = require("app-builder-lib/out/toolsets/7zip");
  const exe = await getPath7za();
  return { exe, license: path.join(path.dirname(exe), "..", "LICENSE.txt") };
}

module.exports = { sevenZip };
