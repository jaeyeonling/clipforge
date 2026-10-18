// electron-builder 설정 (JS 라 환경변수로 분기할 수 있다)
//   npm run pack  → release/win-unpacked/  (설치본 없이 폴더만; packaged 경로·사이드카 점검용)
//   npm run dist  → release/clipforge-Setup-<version>.exe  (NSIS, 사용자 설치·관리자 권한 불필요)
//   CLIPFORGE_SKIP_ENGINE=1 → engine-dist 를 넣지 않는 빠른 빌드 (툴체인 점검용)
"use strict";
const fs = require("node:fs");
const path = require("node:path");

const ENGINE = path.resolve(__dirname, "..", "engine-dist");
const skipEngine = process.env.CLIPFORGE_SKIP_ENGINE === "1";
if (!skipEngine && !fs.existsSync(path.join(ENGINE, "python.exe"))) {
  throw new Error(`engine-dist 가 없습니다: ${ENGINE} — 먼저 python scripts/build_engine_dist.py --smoke`);
}

/** @type {import('electron-builder').Configuration} */
module.exports = {
  appId: "kr.clipforge.app",
  productName: "clipforge",
  copyright: "clipforge. FFmpeg(GPL) 등 제3자 고지는 resources/engine/THIRD_PARTY_NOTICES.md",
  directories: { output: "release", buildResources: "assets" },
  files: ["main.js", "preload.js", "engine.js", "assets/**", "package.json"],
  asar: true,
  extraResources: skipEngine ? [] : [{ from: ENGINE, to: "engine", filter: ["**/*", "!**/__pycache__/**", "!cache/**", "!labels/**", "!review/**", "!premiere/**", "!reports/**", "!videos/**", "!project.json", "!episodes.csv"] }],
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
    allowElevation: false,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: "clipforge",
    runAfterFinish: true,
    deleteAppDataOnUninstall: false,         // 라벨·판정은 지우지 않는다 (§6 원칙)
    installerIcon: "assets/icon.ico",
    uninstallerIcon: "assets/icon.ico",
    uninstallDisplayName: "clipforge",
    language: "1042",                        // 한국어
    differentialPackage: false,              // 4.5GB 블록맵 생성 생략 (업데이터 붙일 때 다시 검토)
  },
  compression: process.env.CLIPFORGE_COMPRESSION || "normal",
  publish: null,                             // 자동 업데이트 서버는 미정 (GitHub Releases 후보)
};
