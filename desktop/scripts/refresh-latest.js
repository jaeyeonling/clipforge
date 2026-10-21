// 설치본을 서명한 뒤 latest.yml 의 sha512 · size 와 .blockmap 을 다시 만든다.
// 서명은 설치본의 바이트를 바꾸므로, 빌드 때 적힌 값으로는 electron-updater 가 내려받은 파일을 거절한다.
//   node scripts/refresh-latest.js <릴리스 폴더>        # latest.yml 이 가리키는 설치본 기준으로 고친다
//   node scripts/refresh-latest.js <릴리스 폴더> --check # 고치지 않고 맞는지만 확인 (틀리면 exit 1)
"use strict";
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const sha512b64 = (file) => crypto.createHash("sha512").update(fs.readFileSync(file)).digest("base64");

/** latest.yml 문자열에서 설치본 이름(path)을 읽고, sha512 · size 를 새 값으로 바꾼 문자열을 돌려준다. */
function patchLatestYml(text, { name, sha512, size }) {
  const m = /^path:\s*(.+)$/m.exec(text);
  if (!m || m[1].trim() !== name) throw new Error(`latest.yml 이 ${name} 을 가리키지 않아요`);
  return text.replace(/^(\s*(?:- )?\s*sha512:\s*).+$/gm, `$1${sha512}`).replace(/^(\s+size:\s*)\d+$/m, `$1${size}`);
}

async function refresh(dir, { check = false } = {}) {
  const ymlPath = path.join(dir, "latest.yml");
  const text = fs.readFileSync(ymlPath, "utf8");
  const name = /^path:\s*(.+)$/m.exec(text)?.[1].trim();
  if (!name) throw new Error("latest.yml 에 path 가 없어요");
  const file = path.join(dir, name);
  const want = { name, sha512: sha512b64(file), size: fs.statSync(file).size };
  const next = patchLatestYml(text, want);
  if (check) return next === text;
  fs.writeFileSync(ymlPath, next, "utf8");
  // 차등 업데이트용 블록 맵도 서명된 파일 기준으로 (electron-builder 가 설치본을 만들 때 쓰는 것과 같은 구현)
  const { buildBlockMap } = require("app-builder-lib/out/targets/blockmap/blockmap");
  await buildBlockMap(file, "gzip", `${file}.blockmap`);
  return true;
}

if (require.main === module) {
  const dir = process.argv[2];
  const check = process.argv.includes("--check");
  if (!dir) {
    console.error("사용: node scripts/refresh-latest.js <릴리스 폴더> [--check]");
    process.exit(2);
  }
  refresh(dir, { check }).then((ok) => {
    console.log(
      check ? (ok ? "[latest.yml] 설치본과 맞아요" : "[latest.yml] 설치본과 달라요") : "[latest.yml] 다시 계산했어요",
    );
    if (!ok) process.exit(1);
  });
}

module.exports = { patchLatestYml, refresh, sha512b64 };
