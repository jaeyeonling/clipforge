// clipforge 데스크톱 껍데기 (Electron)
//   - Python 엔진을 사이드카로 띄우고(engine.js) 준비되면 창에 엔진이 서빙하는 React 화면을 로드
//   - 트레이 상주: 창을 닫아도 작업은 계속, 트레이에서 다시 열기 / 종료
//   - 엔진 /ws 를 구독해 작업 완료·오류를 OS 알림으로
//   - --smoke : 창이 뜨고 엔진이 준비되면 5초 뒤 스스로 종료 (자동 점검용)
"use strict";
const { app, BrowserWindow, Menu, Tray, Notification, shell, dialog, nativeImage } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const WebSocket = require("ws");
const { Engine } = require("./engine");

const SMOKE = process.argv.includes("--smoke");
const ASSETS = path.join(__dirname, "assets");
let win = null, tray = null, engine = null, ws = null, quitting = false, logStream = null;

// ---------- 로그 (userData/shell.log) ----------
function log(line) {
  const msg = `${new Date().toISOString()} ${line}`;
  console.log(msg);
  try { logStream?.write(msg + "\n"); } catch { /* ignore */ }
}

// ---------- 단일 인스턴스 ----------
if (!app.requestSingleInstanceLock()) { app.quit(); }
app.on("second-instance", () => showWindow());

app.setAppUserModelId("kr.clipforge.app");   // Windows 알림에 앱 이름이 나오게

// ---------- 창 ----------
function bootHtml(title, detail, spinning) {
  return `data:text/html;charset=utf-8,` + encodeURIComponent(`<!doctype html><html lang="ko"><meta charset="utf-8">
  <body style="margin:0;background:#0b0a09;color:#f5f2e8;font:14px/1.5 'Malgun Gothic',system-ui;display:flex;align-items:center;justify-content:center;height:100vh">
  <div style="text-align:center;max-width:520px">
    <div style="font-size:28px;font-weight:800;color:#f0f660;letter-spacing:-.02em">clipforge</div>
    <div style="margin-top:14px;font-size:15px">${title}</div>
    <div style="margin-top:8px;color:#8f8979;font-size:12px;white-space:pre-wrap">${detail || ""}</div>
    ${spinning ? `<div style="margin:18px auto 0;width:22px;height:22px;border:3px solid #2c2925;border-top-color:#f0f660;border-radius:50%;animation:s .8s linear infinite"></div><style>@keyframes s{to{transform:rotate(360deg)}}</style>` : ""}
  </div></body></html>`);
}

function createWindow() {
  win = new BrowserWindow({
    width: 1440, height: 900, minWidth: 980, minHeight: 640,
    backgroundColor: "#0b0a09", title: "clipforge", show: false,
    icon: path.join(ASSETS, "icon.png"),
    autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.once("ready-to-show", () => win.show());
  win.loadURL(bootHtml("엔진을 준비하는 중…", "ffmpeg · GPU · 모델을 확인합니다", true));
  // 외부 링크는 시스템 브라우저로
  win.webContents.setWindowOpenHandler(({ url }) => { if (/^https?:/.test(url)) shell.openExternal(url); return { action: "deny" }; });
  win.on("close", (e) => {
    if (quitting) return;
    e.preventDefault(); win.hide();               // 닫기 = 트레이로 (작업은 계속)
    if (!app._hintShown) { app._hintShown = true; notify("트레이에서 계속 실행 중", "작업은 계속됩니다. 트레이 아이콘에서 다시 열거나 종료하세요."); }
  });
  win.on("closed", () => (win = null));
  return win;
}

function showWindow() {
  if (!win) createWindow();
  if (win.isMinimized()) win.restore();
  win.show(); win.focus();
}

// ---------- 트레이 ----------
function createTray() {
  tray = new Tray(nativeImage.createFromPath(path.join(ASSETS, "tray.png")));
  tray.setToolTip("clipforge");
  updateTrayMenu("엔진 준비 중");
  tray.on("click", () => showWindow());
  tray.on("double-click", () => showWindow());
}
function updateTrayMenu(status) {
  if (!tray) return;
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "clipforge 열기", click: () => showWindow() },
    { label: status, enabled: false },
    { type: "separator" },
    { label: "로그 폴더 열기", click: () => shell.openPath(app.getPath("userData")) },
    { label: "브라우저에서 열기", click: () => engine?.port && shell.openExternal(engine.url) },
    { type: "separator" },
    { label: "종료", click: () => quitApp() },
  ]));
}

// ---------- 알림 ----------
function notify(title, body) {
  if (!Notification.isSupported()) return;
  try { new Notification({ title, body, icon: path.join(ASSETS, "icon.png") }).show(); } catch (e) { log(`notify 실패 ${e.message}`); }
}

// ---------- 엔진 이벤트 구독 (작업 완료/오류 알림) ----------
function subscribeEvents() {
  const url = engine.url.replace("http", "ws") + "/ws";
  const connect = () => {
    if (quitting) return;
    ws = new WebSocket(url);
    ws.on("open", () => log("ws: connected"));
    ws.on("message", (raw) => {
      let ev; try { ev = JSON.parse(String(raw)); } catch { return; }
      if (ev.type === "progress") updateTrayMenu(`실행 중: ${ev.stage} ${Math.round(ev.pct || 0)}%`);
      if (ev.type === "done") { updateTrayMenu("대기 중"); if (!win?.isFocused()) notify(ev.status === "cancelled" ? "작업 취소됨" : "작업 완료", `job ${ev.job_id}`); }
      if (ev.type === "error") { updateTrayMenu(`오류: ${ev.code}`); notify(`작업 오류 ${ev.code}`, `${ev.message || ""}\n${ev.hint || ""}`.trim()); }
    });
    ws.on("close", () => { ws = null; if (!quitting) setTimeout(connect, 2000); });
    ws.on("error", (e) => log(`ws: ${e.message}`));
  };
  connect();
}

// ---------- 수명 ----------
async function boot() {
  logStream = fs.createWriteStream(path.join(app.getPath("userData"), "shell.log"), { flags: "a" });
  log(`shell: start electron ${process.versions.electron} node ${process.versions.node} packaged=${app.isPackaged} smoke=${SMOKE}`);
  createWindow();
  createTray();
  engine = new Engine(app, log);
  engine.onExit = (code) => {
    if (quitting) return;
    updateTrayMenu("엔진 종료됨");
    win?.loadURL(bootHtml("엔진이 종료됐습니다", `exit code ${code}\n로그: ${path.join(app.getPath("userData"), "shell.log")}`, false));
  };
  try {
    const h = await engine.start();
    updateTrayMenu(`대기 중 · v${h.engine_version}`);
    const bad = (h.problems || []).filter((p) => p.level === "error");
    if (bad.length) log(`engine: problems ${bad.map((p) => p.code).join(",")}`);
    await win.loadURL(engine.url);
    subscribeEvents();
    log(`shell: ui loaded ${engine.url}`);
    if (SMOKE) { log("smoke: ok — 5초 뒤 종료"); setTimeout(() => quitApp(), 5000); }
  } catch (e) {
    log(`shell: boot 실패 ${e.stack || e}`);
    updateTrayMenu("엔진 시작 실패");
    win?.loadURL(bootHtml("엔진을 시작하지 못했습니다", `${e.message}\n로그: ${path.join(app.getPath("userData"), "shell.log")}`, false));
    if (SMOKE) { setTimeout(() => { quitApp(1); }, 1000); }
    else dialog.showErrorBox("clipforge", `엔진을 시작하지 못했습니다.\n${e.message}`);
  }
}

function quitApp(code = 0) {
  quitting = true;
  try { ws?.close(); } catch { /* ignore */ }
  engine?.stop();
  tray?.destroy();
  app.exit(code);
}

app.whenReady().then(boot);
app.on("window-all-closed", () => { /* 트레이 상주: 창이 다 닫혀도 종료하지 않는다 */ });
app.on("before-quit", () => { quitting = true; engine?.stop(); });
app.on("activate", () => showWindow());
process.on("uncaughtException", (e) => log(`uncaught: ${e.stack || e}`));
