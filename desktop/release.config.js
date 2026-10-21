// 배포 위치 — GitHub Releases, 저장소 jaeyeonling/clipforge (2026-10-18 결정, 일단 **private**).
// main.js(앱 내 업데이트)·electron-builder(껍데기 업데이트)·scripts/publish_github.py 가 같은 값을 쓴다.
//
// private 저장소라 앱이 자산을 받으려면 읽기 전용 토큰이 필요하다:
//   fine-grained PAT (Repository access: clipforge, Permissions: Contents Read-only) 를
//   사용자 PC 의 %LOCALAPPDATA%\clipforge\github-token.txt 에 넣는다 (또는 CLIPFORGE_GH_TOKEN). components.js·main.js 가 읽는다.
//   저장소를 public 으로 바꾸면 토큰 없이 동작한다.
//
// 채널 규칙:
//   - 앱 릴리스  tag v<version>        자산: clipforge-Setup-<ver>.exe, .blockmap, latest.yml(껍데기), engine-code-<ver>.zip, latest.json(앱 내 업데이트)
//   - 런타임     tag runtime-<YYYY.MM>  자산: python-base-*.zip, cuda-*.zip, ffmpeg-*.zip, whisper-*.zip (드물게; 매니페스트가 절대 URL 로 가리킴)
//   latest.json 은 "최신 앱 릴리스"의 자산 → .../releases/latest/download/latest.json
"use strict";
const owner = process.env.CLIPFORGE_GH_OWNER || "jaeyeonling";
const repo = process.env.CLIPFORGE_GH_REPO || "clipforge";
const isPrivate = (process.env.CLIPFORGE_GH_PRIVATE || "1") === "1";

module.exports = {
  owner,
  repo,
  isPrivate,
  updateUrl: `https://github.com/${owner}/${repo}/releases/latest/download`,
  runtimeTag: (yyyymm) => `runtime-${yyyymm}`,
  runtimeUrl: (yyyymm) => `https://github.com/${owner}/${repo}/releases/download/runtime-${yyyymm}`,
};
