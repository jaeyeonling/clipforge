// 껍데기를 실제로 띄워 로그(userData/shell.log)로 확인한다. CI 통합 작업과 로컬에서 같이 쓴다.
//   node scripts/smoke.js dev                     개발 모드: 엔진을 띄우고 화면까지 (--smoke)
//   node scripts/smoke.js setup <exe> <feedDir>   설치본: 빈 런타임으로 첫 실행 설치 화면이 구성요소 목록을 받는지 (--smoke-setup)
"use strict";
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const LOG = path.join(process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming"), "clipforge", "shell.log");
const TIMEOUT_MS = 240_000;

const CHECKS = {
  dev: [/shell: ui loaded http:\/\/127\.0\.0\.1:\d+/, /smoke: 캡처 /],
  setup: [/setup: 받을 구성요소 [1-9]\d*개/, /smoke-setup: 캡처 /],
};

function run(cmd, args, env) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { cwd: path.join(__dirname, ".."), env: { ...process.env, ...env }, stdio: "inherit" });
    const t = setTimeout(() => {
      p.kill();
      reject(new Error(`${TIMEOUT_MS / 1000}초 안에 끝나지 않았어요`));
    }, TIMEOUT_MS);
    p.on("exit", (code) => (clearTimeout(t), resolve(code)));
    p.on("error", reject);
  });
}

async function main() {
  const [mode, exe, feedDir] = process.argv.slice(2);
  if (!CHECKS[mode] || (mode === "setup" && (!exe || !feedDir))) {
    console.error("사용: node scripts/smoke.js dev | setup <exe> <feedDir>");
    process.exit(2);
  }
  const before = fs.existsSync(LOG) ? fs.statSync(LOG).size : 0;
  let code;
  if (mode === "dev") {
    // electron/cli.js 가 바이너리가 없으면 먼저 받는다 (Electron 42+)
    code = await run(process.execPath, [require.resolve("electron/cli.js"), ".", "--smoke"], {});
  } else {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cf-smoke-"));
    code = await run(path.resolve(exe), ["--smoke-setup"], {
      CLIPFORGE_RUNTIME_DIR: path.join(tmp, "runtime"),
      LOCALAPPDATA: tmp,
      CLIPFORGE_UPDATE_URL: pathToFileURL(path.resolve(feedDir)).toString(),
    });
  }
  const log = fs.existsSync(LOG) ? fs.readFileSync(LOG).subarray(before).toString("utf8") : ""; // 바이트 위치로 자른다 (한글)
  console.log("---- shell.log ----\n" + log.trim());
  const missing = CHECKS[mode].filter((re) => !re.test(log));
  if (code !== 0 || missing.length) {
    console.error(`실패: exit ${code}, 로그에 없음: ${missing.map(String).join(", ") || "-"}`);
    process.exit(1);
  }
  console.log(`[smoke ${mode}] 통과`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
