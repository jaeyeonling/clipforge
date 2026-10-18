// Python 엔진 사이드카: 찾기 → 띄우기 → 준비될 때까지 기다리기 → 종료.
// 개발: <repo>/.venv/Scripts/python.exe -m clipforge.app   (cwd = 저장소 루트)
// 배포: <resources>/engine/python.exe -m clipforge.app      (cwd = resources/engine, 포터블 런타임 — 아직 미구성)
// 환경변수: CLIPFORGE_ENGINE_PY(파이썬 경로), CLIPFORGE_ENGINE_CWD, CLIPFORGE_PORT
"use strict";
const { spawn, execFileSync } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

const REPO = path.resolve(__dirname, "..");

function resolveEngine(app) {
  if (process.env.CLIPFORGE_ENGINE_PY) {
    return { py: process.env.CLIPFORGE_ENGINE_PY, cwd: process.env.CLIPFORGE_ENGINE_CWD || REPO };
  }
  if (app.isPackaged) {
    const dir = path.join(process.resourcesPath, "engine");
    return { py: path.join(dir, "python.exe"), cwd: dir };
  }
  const venv = path.join(REPO, ".venv", "Scripts", "python.exe");
  return { py: fs.existsSync(venv) ? venv : "python", cwd: REPO };
}

function httpJson(url, timeoutMs = 1500) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (c) => (body += c));
      res.on("end", () => { try { resolve({ status: res.statusCode, json: JSON.parse(body) }); } catch (e) { reject(e); } });
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
  } catch { /* 안 떠 있음 */ }
  if (await portFree(preferred)) return { port: preferred, external: false };
  for (let p = preferred + 1; p < preferred + 50; p++) if (await portFree(p)) return { port: p, external: false };
  throw new Error("빈 포트를 찾지 못했습니다");
}

class Engine {
  constructor(app, log) {
    this.app = app; this.log = log; this.proc = null; this.port = null; this.external = false; this.health = null;
  }
  get url() { return `http://127.0.0.1:${this.port}`; }

  async start() {
    const preferred = Number(process.env.CLIPFORGE_PORT) || 8765;
    const pick = await pickPort(preferred);
    this.port = pick.port; this.external = pick.external;
    if (pick.external) { this.log(`engine: 이미 떠 있는 엔진에 연결 ${this.url}`); return this.waitReady(5000); }
    const { py, cwd } = resolveEngine(this.app);
    if (!fs.existsSync(py) && py !== "python") throw new Error(`엔진 파이썬을 찾지 못했습니다: ${py}`);
    const args = ["-m", "clipforge.app", "--no-browser", "--port", String(this.port)];
    this.log(`engine: spawn ${py} ${args.join(" ")} (cwd ${cwd})`);
    this.proc = spawn(py, args, { cwd, env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" }, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    this.proc.stdout.on("data", (d) => this.log(`[engine] ${String(d).trimEnd()}`));
    this.proc.stderr.on("data", (d) => this.log(`[engine] ${String(d).trimEnd()}`));
    this.proc.on("exit", (code, sig) => { this.log(`engine: exit code=${code} sig=${sig}`); this.proc = null; if (this.onExit) this.onExit(code); });
    return this.waitReady(60000);
  }

  async waitReady(timeoutMs) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeoutMs) {
      if (!this.external && !this.proc) throw new Error("엔진 프로세스가 시작 직후 종료됐습니다. 로그를 확인하세요.");
      try {
        const r = await httpJson(`${this.url}/api/health`, 2000);
        if (r.status === 200) { this.health = r.json; this.log(`engine: ready v${r.json.engine_version} (${Date.now() - t0}ms)`); return r.json; }
      } catch { /* 아직 */ }
      await new Promise((r) => setTimeout(r, 300));
    }
    throw new Error("엔진이 시간 안에 준비되지 않았습니다");
  }

  stop() {
    if (!this.proc) return;
    const pid = this.proc.pid;
    this.log(`engine: stop pid ${pid}`);
    try {
      if (process.platform === "win32") execFileSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" });
      else this.proc.kill("SIGTERM");
    } catch (e) { this.log(`engine: kill 실패 ${e.message}`); }
    this.proc = null;
  }
}

module.exports = { Engine, httpJson };
