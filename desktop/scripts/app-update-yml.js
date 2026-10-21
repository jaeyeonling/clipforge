// win-unpacked/resources/app-update.yml 을 쓴다 (껍데기 업데이트가 어디를 보고, 어떤 게시자 서명을 믿을지).
// electron-builder 는 설치본을 만들 때만 이 파일을 쓰고, --dir · --prepackaged 로 나눠 만들 때는 쓰지 않는다.
// 서명을 두 번에 나눠 하는 릴리스(앱 exe 서명 → 그 폴더로 설치본)에서 설치본을 만들기 전에 넣는다.
//   node scripts/app-update-yml.js <win-unpacked 폴더>
//   CLIPFORGE_PUBLISHER = 게시자 이름(들, ; 로 구분). 없으면 서명 확인 없이 업데이트한다.
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const release = require("../src/release.config");
const pkg = require("../package.json");

function appUpdateYml(env = process.env) {
  const names = (env.CLIPFORGE_PUBLISHER || "")
    .split(";")
    .map((s) => s.trim())
    .filter(Boolean);
  const q = (s) => JSON.stringify(s); // YAML 은 JSON 문자열을 그대로 읽는다 (쉼표·공백이 있는 CN 도 안전)
  return [
    `owner: ${q(release.owner)}`,
    `repo: ${q(release.repo)}`,
    "provider: github",
    "releaseType: release",
    `updaterCacheDirName: ${q(`${pkg.name.toLowerCase()}-updater`)}`,
    ...(names.length ? ["publisherName:", ...names.map((n) => `  - ${q(n)}`)] : []),
    "",
  ].join("\n");
}

if (require.main === module) {
  const dir = process.argv[2];
  if (!dir || !fs.existsSync(path.join(dir, "resources"))) {
    console.error("사용: node scripts/app-update-yml.js <win-unpacked 폴더>");
    process.exit(2);
  }
  const out = path.join(dir, "resources", "app-update.yml");
  fs.writeFileSync(out, appUpdateYml(), "utf8");
  console.log(`[app-update.yml] ${out}\n${appUpdateYml()}`);
}

module.exports = { appUpdateYml };
