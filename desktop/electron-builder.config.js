// electron-builder 설정 (JS 라 환경변수로 분기할 수 있다)
//   npm run pack  → release/win-unpacked/  (설치본 없이 폴더만; packaged 경로·사이드카 점검용)
//   npm run dist  → release/clipforge-Setup-<version>.exe  (NSIS, 사용자 설치·관리자 권한 불필요)
//
// 설치본은 **작다**: Electron + 엔진 코드(층 A: clipforge/ games/ data/ assets/ app/dist, ~5MB) + 7za.exe.
// 대용량 구성요소(파이썬 런타임·CUDA·ffmpeg·Whisper 모델, 층 B)는 첫 실행 때 components.js 가 받아 %LOCALAPPDATA%\clipforge\runtime 에 놓는다.
//   CLIPFORGE_SKIP_ENGINE=1 → 엔진 코드도 넣지 않는 빠른 빌드 (툴체인 점검용)
"use strict";
const fs = require("node:fs");
const path = require("node:path");

const ENGINE = path.resolve(__dirname, "..", "engine-dist");
const skipEngine = process.env.CLIPFORGE_SKIP_ENGINE === "1";
if (!skipEngine && !fs.existsSync(path.join(ENGINE, "clipforge", "app.py"))) {
  throw new Error(`engine-dist 가 없습니다: ${ENGINE} — 먼저 python scripts/build_engine_dist.py`);
}
const CODE = ["clipforge/**", "games/**", "data/**", "assets/**", "app/dist/**", "VERSION.json", "THIRD_PARTY_NOTICES.md"];

/** @type {import('electron-builder').Configuration} */
module.exports = {
  appId: "kr.clipforge.app",
  productName: "clipforge",
  copyright: "clipforge. 제3자 고지는 resources/engine/THIRD_PARTY_NOTICES.md (FFmpeg GPL 등은 첫 실행 때 내려받는 구성요소에 포함)",
  directories: { output: "release", buildResources: "assets" },
  files: ["main.js", "preload.js", "engine.js", "components.js", "release.config.js", "assets/**", "package.json"],
  asar: true,
  extraResources: [
    ...(skipEngine ? [] : [{ from: ENGINE, to: "engine", filter: [...CODE, "!**/__pycache__/**"] }]),
    { from: "node_modules/7zip-bin/win/x64/7za.exe", to: "7za.exe" },
    { from: "node_modules/7zip-bin/LICENSE", to: "7za-LICENSE.txt" },
  ],
  // 서명 없음(코드 서명 인증서는 배포 결정 뒤). rcedit 로 아이콘·버전 정보는 넣는다.
  win: {
    target: [{ target: "nsis", arch: ["x64"] }],
    icon: "assets/icon.ico",
    artifactName: "${productName}-Setup-${version}.${ext}",
    signAndEditExecutable: process.env.CLIPFORGE_NO_RCEDIT !== "1",
  },
  nsis: {
    oneClick: false,
    perMachine: false,                       // 사용자 폴더(%LOCALAPPDATA%\Programs) 설치 → UAC 없음
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: "clipforge",
    runAfterFinish: true,
    deleteAppDataOnUninstall: false,         // 라벨·판정·런타임은 지우지 않는다 (§6 원칙)
    installerIcon: "assets/icon.ico",
    uninstallerIcon: "assets/icon.ico",
    uninstallDisplayName: "clipforge",
    language: "1042",                        // 한국어
    differentialPackage: true,               // 껍데기(층 C) 차등 업데이트용 blockmap
  },
  compression: process.env.CLIPFORGE_COMPRESSION || "normal",
  // 껍데기(층 C) 업데이트: electron-updater 가 GitHub Releases 의 latest.yml 을 본다. 빌드 때 app-update.yml 로 들어간다.
  // 실제 업로드는 scripts/publish_github.py(gh CLI)가 한다 — electron-builder 의 --publish 는 쓰지 않는다(GH_TOKEN 불필요).
  publish: { provider: "github", owner: require("./release.config").owner, repo: require("./release.config").repo, releaseType: "release" },
};
