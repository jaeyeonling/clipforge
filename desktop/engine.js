// Python 엔진 사이드카: 어디서 띄울지 정하고 → 띄우고 → 준비될 때까지 기다리고 → 끝낼 때 정리.
//
// 실행 모드 (resolveEngine):
//   runtime  : <runtimeDir>/python.exe -m clipforge.app   ← 설치본. runtimeDir = %LOCALAPPDATA%\clipforge\runtime (첫 실행 때 구성요소를 받아 채움)
//   dist     : <repo>/engine-dist/python.exe              ← 개발 중 번들 점검 (CLIPFORGE_ENGINE_DIST=1)
//   venv     : <repo>/.venv/Scripts/python.exe            ← 개발 기본
// 환경변수: CLIPFORGE_ENGINE_PY(파이썬 직접 지정) CLIPFORGE_ENGINE_CWD CLIPFORGE_RUNTIME_DIR CLIPFORGE_DATA CLIPFORGE_PORT
"use strict";
const { spawn, execFileSync } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

const REPO = path.resolve(__dirname, "..");

function localAppData() {
  return process.env.LOCALAPPDATA || path.join(require("node:os").homedir(), "AppData", "Local");
}

/** 설치본·런타임 모드의 기본 폴더. 데이터(영상 캐시 수 GB)와 런타임(4GB)은 Roaming 이 아니라 Local 에 둔다. */
function defaultDirs() {
  const base = path.join(localAppData(), "clipforge");
  return {
    runtime: process.env.CLIPFORGE_RUNTIME_DIR || path.join(base, "runtime"),
    data: process.env.CLIPFORGE_DATA || path.join(base, "data"),
    downloads: path.join(base, "downloads"),
  };
}

/** { mode, py, cwd, dataRoot, runtimeDir, seedDir } */
function resolveEngine(app) {
  const dirs = defaultDirs();
  if (process.env.CLIPFORGE_ENGINE_PY) {
    return {
      mode: "custom",
      py: process.env.CLIPFORGE_ENGINE_PY,
      cwd: process.env.CLIPFORGE_ENGINE_CWD || REPO,
      dataRoot: process.env.CLIPFORGE_DATA,
    };
  }
  if (app.isPackaged || process.env.CLIPFORGE_RUNTIME_DIR) {
    const seed = app.isPackaged ? path.join(process.resourcesPath, "engine") : path.join(REPO, "engine-dist");
    return {
      mode: "runtime",
      py: path.join(dirs.runtime, "python.exe"),
      cwd: dirs.runtime,
      dataRoot: dirs.data,
      runtimeDir: dirs.runtime,
      seedDir: seed,
      downloads: dirs.downloads,
    };
  }
  if (process.env.CLIPFORGE_ENGINE_DIST === "1") {
    const dir = path.join(REPO, "engine-dist");
    return { mode: "dist", py: path.join(dir, "python.exe"), cwd: dir, dataRoot: REPO }; // 데이터는 저장소(ep59 등), 번들은 깨끗하게
  }
  const venv = path.join(REPO, ".venv", "Scripts", "python.exe");
  return { mode: "venv", py: fs.existsSync(venv) ? venv : "python", cwd: REPO, dataRoot: process.env.CLIPFORGE_DATA };
}

function httpJson(url, timeoutMs = 1500) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (c) => (body += c));
      res.on("end", () => {
        try {
          resolve({ status: res.statusCode, json: JSON.parse(body) });
        } catch (e) {
          reject(e);
        }
      });
    });
    req.on("timeout", () => req.destroy(new Error("timeout")));
    req.on("error", reject);
  });
}

function portFree(port) {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.once("error", () => resolve(false));
    s.once("listening", () => s.close(() => resolve(true)));
    s.listen(port, "127.0.0.1");
  });
}

async function pickPort(preferred) {
  // 이미 우리 엔진이 떠 있으면(개발 중 터미널에서 띄운 경우) 그대로 붙는다
  try {
    const r = await httpJson(`http://127.0.0.1:${preferred}/api/health`);
    if (r.status === 200 && r.json && r.json.engine_version) return { port: preferred, external: true };
  } catch {
    /* 안 떠 있음 */
  }
  if (await portFree(preferred)) return { port: preferred, external: false };
  for (let p = preferred + 1; p < preferred + 50; p++) if (await portFree(p)) return { port: p, external: false };
  throw new Error("빈 포트를 찾지 못했습니다");
}

class Engine {
  constructor(app, log) {
    this.app = app;
    this.log = log;
    this.proc = null;
    this.port = null;
    this.external = false;
    this.health = null;
    this.cfg = resolveEngine(app);
  }
  get url() {
    return `http://127.0.0.1:${this.port}`;
  }

  async start() {
    const preferred = Number(process.env.CLIPFORGE_PORT) || 8765;
    const pick = await pickPort(preferred);
    this.port = pick.port;
    this.external = pick.external;
    if (pick.external) {
      this.log(`engine: 이미 떠 있는 엔진에 연결 ${this.url}`);
      return this.waitReady(5000);
    }
    const { py, cwd, dataRoot } = this.cfg;
    if (!fs.existsSync(py) && py !== "python") throw new Error(`엔진 파이썬을 찾지 못했습니다: ${py}`);
    const args = ["-m", "clipforge.app", "--no-browser", "--port", String(this.port)];
    const env = { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" };
    if (dataRoot) {
      fs.mkdirSync(dataRoot, { recursive: true });
      env.CLIPFORGE_DATA = dataRoot;
    } // 사용자 데이터는 앱·런타임 폴더 밖
    this.log(
      `engine: spawn [${this.cfg.mode}] ${py} ${args.join(" ")} (cwd ${cwd}${env.CLIPFORGE_DATA ? ", data " + env.CLIPFORGE_DATA : ""})`,
    );
    this.proc = spawn(py, args, { cwd, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    this.proc.stdout.on("data", (d) => this.log(`[engine] ${String(d).trimEnd()}`));
    this.proc.stderr.on("data", (d) => this.log(`[engine] ${String(d).trimEnd()}`));
    this.proc.on("exit", (code, sig) => {
      this.log(`engine: exit code=${code} sig=${sig}`);
      this.proc = null;
      if (this.onExit) this.onExit(code);
    });
    return this.waitReady(60000);
  }

  async waitReady(timeoutMs) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeoutMs) {
      if (!this.external && !this.proc) throw new Error("엔진 프로세스가 시작 직후 종료됐습니다. 로그를 확인하세요.");
      try {
        const r = await httpJson(`${this.url}/api/health`, 2000);
        if (r.status === 200) {
          this.health = r.json;
          this.log(`engine: ready v${r.json.engine_version} (${Date.now() - t0}ms)`);
          return r.json;
        }
      } catch {
        /* 아직 */
      }
      await new Promise((r) => setTimeout(r, 300));
    }
    throw new Error("엔진이 시간 안에 준비되지 않았습니다");
  }

  /** 엔진을 멈추고 프로세스가 사라질 때까지 기다린다 (구성요소 교체 전에 필요) */
  async stopAndWait() {
    this.stop();
    for (let i = 0; i < 50; i++) {
      try {
        await httpJson(`${this.url}/api/health`, 500);
      } catch {
        return;
      }
      await new Promise((r) => setTimeout(r, 100));
    }
  }

  stop() {
    if (!this.proc) return;
    const pid = this.proc.pid;
    this.log(`engine: stop pid ${pid}`);
    try {
      if (process.platform === "win32")
        execFileSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" });
      else this.proc.kill("SIGTERM");
    } catch (e) {
      this.log(`engine: kill 실패 ${e.message}`);
    }
    this.proc = null;
  }
}

module.exports = { Engine, httpJson, resolveEngine, defaultDirs };
