// clipforge 데스크톱 껍데기 (Electron)
//   - 설치본 모드(runtime): %LOCALAPPDATA%\clipforge\runtime 에 엔진 코드(동봉) + 구성요소(첫 실행 때 다운로드)를 두고 거기서 엔진을 띄운다
//   - 개발 모드(venv/dist): 저장소의 파이썬으로 바로 띄운다
//   - 창: 부팅/설치 화면 → 엔진 URL 로드. 닫기 = 트레이로. 트레이에서 열기/업데이트/종료
//   - /ws 구독 → 트레이 상태·OS 알림.  6시간마다 latest.json 확인 → 업데이트 있으면 알림 + 트레이 메뉴 "업데이트 적용"
//   - --smoke : 준비 뒤 5초 후 종료 (자동 점검).  --smoke-setup : 설치 화면까지만 띄우고 종료하지 않음 (화면 점검)
"use strict";
const { app, BrowserWindow, Menu, Tray, Notification, shell, dialog, nativeImage, ipcMain, globalShortcut } = require("electron");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const WebSocket = require("ws");
const { Engine } = require("./engine");
const C = require("./components");
const RELEASE = require("./release.config");

const SMOKE = process.argv.includes("--smoke");
const AUTO_SETUP = process.argv.includes("--auto-setup");
const AUTO_UPDATE = process.argv.includes("--auto-update");   // 시작 직후 업데이트를 확인해 있으면 바로 적용 (자동 점검용)   // 설치 화면에서 기본 선택으로 자동 시작 (자동 점검용)
const ASSETS = path.join(__dirname, "assets");
const DEFAULT_UPDATE_URL = RELEASE.updateUrl;      // GitHub Releases: <owner>/<repo> 의 최신 릴리스 자산 (release.config.js)
let win = null, tray = null, engine = null, ws = null, quitting = false, logStream = null;
let pendingUpdates = [];           // plan() 결과 중 아직 적용 안 한 것 (층 A·B)
let shellUpdate = null;            // electron-updater 가 내려받아 둔 껍데기 새 버전 (층 C) {version}
const updateState = { checking: false, applying: false, lastCheck: null, error: null, progress: null };
function broadcastUpdate() {
  const st = { ...updateState, shell: shellUpdate,
    pending: pendingUpdates.map((u) => ({ name: u.name, version: u.entry.version, size: u.entry.size || 0, reason: u.reason, notes: u.entry.notes || "" })) };
  try { win?.webContents.send("update:state", st); } catch { /* 창 없음 */ }
  return st;
}
let setupState = null;             // 첫 실행 설치 진행 상태
let jobRunning = false;

// ---------- 로그 (userData/shell.log) ----------
function log(line) {
  const msg = `${new Date().toISOString()} ${line}`;
  console.log(msg);
  try { logStream?.write(msg + "\n"); } catch { /* ignore */ }
}

if (!app.requestSingleInstanceLock()) { app.quit(); }
app.on("second-instance", () => showWindow());
app.setAppUserModelId("kr.clipforge.app");

// ---------- 업데이트 서버 주소 ----------
function updateUrl() {
  if (process.env.CLIPFORGE_UPDATE_URL) return process.env.CLIPFORGE_UPDATE_URL;
  // 오프라인/USB 설치: %LOCALAPPDATA%\clipforge\update-url.txt 에 file:///E:/clipforge-release 같은 주소를 적어 두면 거기서 받는다
  try {
    const p = path.join(process.env.LOCALAPPDATA || "", "clipforge", "update-url.txt");
    const t = fs.readFileSync(p, "utf8").trim(); if (t) return t;
  } catch { /* none */ }
  return DEFAULT_UPDATE_URL;
}

// ---------- 창 ----------
const PAGE_CSS = `body{margin:0;background:#0b0a09;color:#f5f2e8;font:14px/1.5 'Malgun Gothic',system-ui;display:flex;align-items:center;justify-content:center;height:100vh}
.box{max-width:640px;width:92%}.brand{font-size:28px;font-weight:800;color:#f0f660;letter-spacing:-.02em}.t{margin-top:14px;font-size:16px;font-weight:700}
.d{margin-top:6px;color:#8f8979;font-size:12px;white-space:pre-wrap}.spin{margin:18px auto 0;width:22px;height:22px;border:3px solid #2c2925;border-top-color:#f0f660;border-radius:50%;animation:s .8s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}table{width:100%;border-collapse:collapse;margin-top:16px;font-size:13px}td{padding:8px 6px;border-bottom:1px solid #2c2925;vertical-align:middle}
td.n{width:28px}td.s{color:#8f8979;white-space:nowrap;text-align:right;width:90px}.bar{height:6px;background:#1a1816;border-radius:4px;overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;width:0;background:#f0f660;transition:width .2s}
.st{font-size:11px;color:#8f8979;margin-top:2px}.ok{color:#9be28a}.bad{color:#ff7b70}.btns{display:flex;gap:8px;margin-top:16px;justify-content:flex-end}
button{font:inherit;border-radius:6px;border:1px solid #3a3631;background:#211e1b;color:#f5f2e8;padding:8px 14px;cursor:pointer}button.p{background:#f0f660;color:#1a1a10;border-color:#f0f660;font-weight:700}button:disabled{opacity:.45;cursor:default}
input[type=checkbox]{accent-color:#f0f660}.hint{font-size:12px;color:#8f8979;margin-top:10px}`;

function dataUrl(html) { return "data:text/html;charset=utf-8," + encodeURIComponent(`<!doctype html><html lang="ko"><meta charset="utf-8"><style>${PAGE_CSS}</style><body>${html}</body></html>`); }

function bootHtml(title, detail, spinning) {
  return dataUrl(`<div class="box" style="text-align:center"><div class="brand">clipforge</div><div class="t">${title}</div><div class="d">${detail || ""}</div>${spinning ? '<div class="spin"></div>' : ""}</div>`);
}

// 첫 실행 설치 화면: 구성요소 목록·선택·진행률. 데이터는 setup:event 로 받는다.
function setupHtml() {
  return dataUrl(`<div class="box"><div class="brand">clipforge</div><div class="t" id="title">처음 실행: 분석 엔진 구성요소를 내려받습니다</div>
<div class="d" id="desc">한 번만 받습니다. 이후 업데이트는 바뀐 부분만 받습니다.</div>
<table id="tb"></table><div class="hint" id="hint"></div>
<div class="btns"><button id="logs">로그 폴더</button><button id="retry" style="display:none">다시 시도</button><button id="start" class="p" disabled>설치 시작</button></div></div>
<script>
const S = window.clipforgeShell.setup; const $ = (s) => document.querySelector(s);
const human = (n) => n >= 1e9 ? (n/1e9).toFixed(1)+'GB' : n >= 1e6 ? Math.round(n/1e6)+'MB' : Math.round(n/1e3)+'KB';
let items = [], running = false;
function render() {
  $('#tb').innerHTML = items.map((it, i) => \`<tr data-n="\${it.name}"><td class="n"><input type="checkbox" \${it.selected ? 'checked' : ''} \${it.optional && !running ? '' : 'disabled'} data-i="\${i}"></td>
    <td><div>\${it.label}</div><div class="bar"><i style="width:\${it.pct || 0}%"></i></div><div class="st">\${it.status || (it.reason === 'update' ? '업데이트' : '새로 설치')}</div></td><td class="s">\${human(it.size || 0)}</td></tr>\`).join('');
  const total = items.filter((x) => x.selected).reduce((a, x) => a + (x.size || 0), 0);
  $('#hint').textContent = running ? '' : '선택한 구성요소 합계 ' + human(total) + ' — 네트워크 속도에 따라 수 분~수십 분 걸립니다. 받는 동안 창을 닫아도 계속됩니다.';
  $('#start').disabled = running || !items.some((x) => x.selected);
  document.querySelectorAll('input[data-i]').forEach((el) => el.onchange = () => { items[Number(el.dataset.i)].selected = el.checked; render(); });
}
S.onEvent((ev) => {
  if (ev.type === 'plan') { items = ev.items; $('#title').textContent = ev.title || $('#title').textContent; if (ev.desc) $('#desc').textContent = ev.desc; render(); return; }
  const it = items.find((x) => x.name === ev.name); if (!it) return;
  if (ev.type === 'start') { running = true; it.status = '받는 중…'; it.pct = 0; }
  if (ev.type === 'download') { it.pct = ev.total ? Math.round(100 * ev.done / ev.total) : 0; it.status = ev.cached ? '이미 받음' : '받는 중 ' + human(ev.done) + ' / ' + human(ev.total); }
  if (ev.type === 'install') { it.status = ev.phase === 'extract' ? '푸는 중' + (ev.pct != null ? ' ' + ev.pct + '%' : '') : '교체 중'; it.pct = 100; }
  if (ev.type === 'done') { it.status = '<span class="ok">완료</span>'; it.pct = 100; }
  if (ev.type === 'error') { running = false; it.status = '<span class="bad">실패: ' + ev.message + '</span>'; $('#retry').style.display = ''; }
  render();
});
$('#start').onclick = () => { running = true; $('#retry').style.display = 'none'; render(); S.start({ optional: Object.fromEntries(items.filter((x) => x.optional).map((x) => [x.name, !!x.selected])) }); };
$('#retry').onclick = () => $('#start').onclick();
$('#logs').onclick = () => S.openLogs();
S.ready();
</script>`);
}

function createWindow() {
  win = new BrowserWindow({
    width: 1440, height: 900, minWidth: 980, minHeight: 640,
    backgroundColor: "#0b0a09", title: "clipforge", show: false,
    icon: path.join(ASSETS, "icon.png"), autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.once("ready-to-show", () => win.show());
  win.loadURL(bootHtml("엔진을 준비하는 중…", "", true));
  win.webContents.setWindowOpenHandler(({ url }) => { if (/^https?:/.test(url)) shell.openExternal(url); return { action: "deny" }; });
  win.on("close", (e) => {
    if (quitting) return;
    e.preventDefault(); win.hide();
    if (!app._hintShown) { app._hintShown = true; notify("트레이에서 계속 실행 중", "작업과 다운로드는 계속됩니다. 트레이 아이콘에서 다시 열거나 종료하세요."); }
  });
  win.on("closed", () => (win = null));
  return win;
}
function showWindow() { if (!win) createWindow(); if (win.isMinimized()) win.restore(); win.show(); win.focus(); }

// ---------- 트레이 ----------
function createTray() {
  tray = new Tray(nativeImage.createFromPath(path.join(ASSETS, "tray.png")));
  tray.setToolTip("clipforge");
  updateTrayMenu("엔진 준비 중");
  tray.on("click", () => showWindow());
}
let trayStatus = "";
function updateTrayMenu(status) {
  if (status != null) trayStatus = status;
  if (!tray) return;
  const upd = pendingUpdates.length ? [{ label: `업데이트 적용 (${pendingUpdates.map((u) => u.name).join(", ")})`, enabled: !jobRunning, click: () => applyUpdates().catch((e) => log(`update: ${e.message}`)) }] : [];
  if (shellUpdate) upd.push({ label: `앱 ${shellUpdate.version} 설치하고 다시 시작`, enabled: !jobRunning, click: () => installShellUpdate() });
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "clipforge 열기", click: () => showWindow() },
    { label: trayStatus, enabled: false },
    ...upd,
    { label: "업데이트 확인", click: () => checkUpdates(true).catch((e) => log(`update: ${e.message}`)) },
    { type: "separator" },
    { label: "로그 폴더 열기", click: () => shell.openPath(app.getPath("userData")) },
    { label: "브라우저에서 열기", click: () => engine?.port && shell.openExternal(engine.url) },
    { type: "separator" },
    { label: "종료", click: () => quitApp() },
  ]));
}

function notify(title, body) {
  if (!Notification.isSupported()) return;
  try { new Notification({ title, body, icon: path.join(ASSETS, "icon.png") }).show(); } catch (e) { log(`notify 실패 ${e.message}`); }
}

// ---------- 엔진 이벤트 구독 ----------
function subscribeEvents() {
  const url = engine.url.replace("http", "ws") + "/ws";
  const connect = () => {
    if (quitting || !engine?.port) return;
    ws = new WebSocket(url);
    ws.on("open", () => log("ws: connected"));
    ws.on("message", (raw) => {
      let ev; try { ev = JSON.parse(String(raw)); } catch { return; }
      if (ev.type === "started" || ev.type === "progress") { jobRunning = true; updateTrayMenu(`실행 중: ${ev.stage || ""} ${Math.round(ev.pct || 0)}%`); }
      if (ev.type === "done") { jobRunning = false; updateTrayMenu("대기 중"); if (!win?.isFocused()) notify(ev.status === "cancelled" ? "작업 취소됨" : "작업 완료", `job ${ev.job_id}`); }
      if (ev.type === "error") { jobRunning = false; updateTrayMenu(`오류: ${ev.code}`); notify(`작업 오류 ${ev.code}`, `${ev.message || ""}\n${ev.hint || ""}`.trim()); }
      // 라이브 제안: 게임 중이라 앱 창을 못 보는 사람에게 OS 알림 + 단축키 안내
      if (ev.type === "live" && ev.event) {
        const le = ev.event;
        if (le.type === "suggestion" && le.status === "pending" && !win?.isFocused()) notify(`득템 제안: ${le.head || le.text} (${le.grade})`, "Ctrl+Alt+Y 배너에 추가 · Ctrl+Alt+N 무시");
        if (le.type === "started") liveActive = true;
        if (le.type === "stopped") liveActive = false;
      }
    });
    ws.on("close", () => { ws = null; if (!quitting) setTimeout(connect, 2000); });
    ws.on("error", (e) => log(`ws: ${e.message}`));
  };
  connect();
}

// ---------- 첫 실행 설치 (runtime 모드) ----------
function sendSetup(ev) { win?.webContents.send("setup:event", ev); }

async function ensureRuntime() {
  const cfg = engine.cfg;
  if (cfg.mode !== "runtime") return;
  fs.mkdirSync(cfg.runtimeDir, { recursive: true });
  if (!C.present(cfg.runtimeDir, "engine_code")) {
    const ok = await C.seedFromResources(cfg.runtimeDir, cfg.seedDir);
    log(`runtime: engine code seed ${ok ? "ok" : "없음"} ← ${cfg.seedDir}`);
  }
  const need = ["python-base", "ffmpeg", "whisper"].filter((n) => !C.present(cfg.runtimeDir, n));
  if (!need.length) return;                      // 구성 완료 → 평소처럼 엔진 시작
  log(`runtime: 구성요소 필요 ${need.join(",")} → 설치 화면`);
  await runSetup(cfg);
}

function hasNvidia() {
  try { require("node:child_process").execFileSync("nvidia-smi", ["-L"], { stdio: "ignore", windowsHide: true }); return true; } catch { return false; }
}

function runSetup(cfg) {
  return new Promise((resolve, reject) => {
    let manifest = null, abort = null;
    setupState = { resolve, reject };
    const sendPlan = async () => {
      try {
        manifest = await C.fetchManifest(updateUrl());
        const gpu = hasNvidia();
        const items = C.plan(cfg.runtimeDir, manifest, {}).filter((it) => it.kind === "component").map((it) => ({
          name: it.name, label: it.entry.label || it.name, size: it.entry.size, optional: !!it.entry.optional, reason: it.reason,
          selected: it.entry.optional ? gpu : true,
        }));
        sendSetup({ type: "plan", items, desc: gpu ? "NVIDIA GPU 가 감지되어 GPU 가속을 함께 받습니다." : "NVIDIA GPU 가 없어 GPU 가속은 선택에서 뺐습니다 (CPU 로도 동작, 전사만 느립니다)." });
      } catch (e) {
        log(`setup: manifest 실패 ${e.message}`);
        const tokenHint = RELEASE.isPrivate && !C.githubToken() ? "\n비공개 저장소라 토큰이 필요합니다: %LOCALAPPDATA%\\clipforge\\github-token.txt 에 읽기 전용 토큰을 넣고 다시 시도하세요." : "";
        sendSetup({ type: "plan", items: [], title: "구성요소 목록을 받지 못했습니다", desc: `${e.message}\n서버: ${updateUrl()}${tokenHint}\n네트워크를 확인한 뒤 다시 시도하세요.` });
      }
    };
    ipcMain.removeHandler("setup:ready"); ipcMain.removeHandler("setup:start"); ipcMain.removeHandler("setup:cancel");
    ipcMain.handle("setup:ready", async () => { await sendPlan(); if (AUTO_SETUP && manifest) startInstall({ optional: { cuda: hasNvidia() } }); });
    ipcMain.handle("setup:cancel", () => { abort?.abort(); });
    ipcMain.handle("setup:start", (_e, opts) => startInstall(opts));
    const startInstall = async (opts) => {
      if (!manifest) { await sendPlan(); if (!manifest) return; }
      const items = C.plan(cfg.runtimeDir, manifest, { wantOptional: opts.optional || {} }).filter((it) => it.kind === "component");
      abort = new AbortController();
      updateTrayMenu("구성요소 내려받는 중");
      try {
        await C.apply(cfg.runtimeDir, items, { downloadDir: cfg.downloads, signal: abort.signal, onEvent: (ev) => { sendSetup(ev); if (ev.type === "download" && ev.total) updateTrayMenu(`내려받는 중 ${ev.name} ${Math.round(100 * ev.done / ev.total)}%`); } });
        log("setup: 완료");
        setupState = null; resolve();
      } catch (e) {
        log(`setup: 실패 ${e.stack || e}`);
        sendSetup({ type: "error", name: items.find((it) => !C.present(cfg.runtimeDir, it.name))?.name || items[0]?.name, message: e.message });
        if (SMOKE) { setupState = null; reject(e); }
      }
    };
    win.loadURL(setupHtml());
    showWindow();
  });
}

// ---------- 껍데기 업데이트 (층 C, electron-updater · GitHub Releases latest.yml) ----------
let autoUpdater = null;
function setupShellUpdater() {
  if (!app.isPackaged) { log("shell-update: 개발 모드 — 건너뜀"); return; }
  try { ({ autoUpdater } = require("electron-updater")); } catch (e) { log(`shell-update: electron-updater 없음 ${e.message}`); return; }
  autoUpdater.logger = { info: (m) => log(`shell-update: ${m}`), warn: (m) => log(`shell-update: ${m}`), error: (m) => log(`shell-update: ${m}`), debug: () => {} };
  autoUpdater.autoDownload = true;              // 껍데기는 ~90MB, 조용히 받아 둔다
  autoUpdater.autoInstallOnAppQuit = true;      // 종료 때 설치. 강제 재시작은 하지 않는다 (방송 방해 금지)
  autoUpdater.allowDowngrade = false;
  const token = C.githubToken();
  if (RELEASE.isPrivate) {
    if (!token) { log("shell-update: private 저장소인데 토큰이 없습니다 — 껍데기 업데이트 비활성 (github-token.txt)"); autoUpdater = null; return; }
    autoUpdater.setFeedURL({ provider: "github", owner: RELEASE.owner, repo: RELEASE.repo, private: true, token });
  }
  autoUpdater.on("update-available", (info) => log(`shell-update: available ${info.version}`));
  autoUpdater.on("update-not-available", () => log("shell-update: 최신"));
  autoUpdater.on("error", (e) => log(`shell-update: error ${e?.message || e}`));
  autoUpdater.on("update-downloaded", (info) => {
    shellUpdate = { version: info.version };
    updateTrayMenu(null); broadcastUpdate();
    notify(`앱 ${info.version} 준비됨`, "다음에 종료할 때 자동으로 설치됩니다. 지금 설치하려면 트레이 메뉴에서 선택하세요.");
  });
}
async function checkShellUpdate() {
  if (!autoUpdater) return null;
  try { const r = await autoUpdater.checkForUpdates(); return r?.updateInfo?.version || null; } catch (e) { log(`shell-update: check 실패 ${e.message}`); return null; }
}
function installShellUpdate() {
  if (!autoUpdater || !shellUpdate || jobRunning) return;
  quitting = true;
  try { ws?.close(); } catch { /* ignore */ }
  engine?.stop();
  autoUpdater.quitAndInstall(false, true);
}

// ---------- 앱 내 업데이트 (층 A·B) ----------
async function checkUpdates(interactive = false) {
  const cfg = engine?.cfg;
  if (!cfg || cfg.mode !== "runtime") { if (interactive) notify("업데이트", "개발 모드에서는 업데이트를 확인하지 않습니다."); updateState.error = "dev"; broadcastUpdate(); return; }
  updateState.checking = true; updateState.error = null; broadcastUpdate();
  let manifest;
  try { manifest = await C.fetchManifest(updateUrl()); }
  catch (e) { updateState.checking = false; updateState.error = e.message; updateState.lastCheck = Date.now(); broadcastUpdate(); throw e; }
  const local = C.readLocalVersion(cfg.runtimeDir) || {};
  const want = Object.fromEntries(Object.keys(manifest.components || {}).map((n) => [n, C.present(cfg.runtimeDir, n)]));   // 설치된 것만 갱신 (cuda 안 받았으면 계속 안 받음)
  pendingUpdates = C.plan(cfg.runtimeDir, manifest, { wantOptional: want }).filter((it) => it.reason === "update");
  log(`update: local ${local.engine_version} → 매니페스트 ${manifest.engine_code?.version}; 대기 ${pendingUpdates.map((u) => `${u.name}@${u.entry.version}`).join(",") || "없음"}`);
  updateState.checking = false; updateState.lastCheck = Date.now();
  updateTrayMenu(null); broadcastUpdate();
  if (pendingUpdates.length) {
    const size = pendingUpdates.reduce((a, u) => a + (u.entry.size || 0), 0);
    notify("업데이트 있음", `${pendingUpdates.map((u) => u.name).join(", ")} (${(size / 1e6).toFixed(0)}MB). 트레이 메뉴에서 적용하세요.${jobRunning ? " 작업이 끝난 뒤 적용됩니다." : ""}`);
  } else if (interactive) notify("업데이트", "최신 상태입니다.");
  return pendingUpdates;
}

async function applyUpdates() {
  if (!pendingUpdates.length || jobRunning) return;
  const cfg = engine.cfg;
  const items = pendingUpdates.slice();
  updateTrayMenu("업데이트 적용 중");
  updateState.applying = true; updateState.error = null; broadcastUpdate();
  // 1) 먼저 내려받는다 (엔진은 계속 떠 있음 → 화면이 진행률을 보여준다)
  const zips = {};
  try {
    for (const u of items) {
      const zip = path.join(cfg.downloads, path.basename(new URL(u.entry.url).pathname));
      await C.download(u.entry, zip, (pr) => { updateState.progress = { name: u.name, done: pr.done, total: pr.total }; broadcastUpdate(); });
      zips[u.name] = zip;
    }
  } catch (e) {
    log(`update: 다운로드 실패 ${e.stack || e}`);
    updateState.applying = false; updateState.progress = null; updateState.error = e.message; broadcastUpdate();
    notify("업데이트 실패", e.message); updateTrayMenu("대기 중"); return;
  }
  // 2) 엔진을 멈추고 교체 → 재시작 (수 초)
  win?.loadURL(bootHtml("업데이트를 적용하는 중…", items.map((u) => `${u.name} → ${u.entry.version}`).join("\n"), true));
  await engine.stopAndWait();
  try {
    for (const u of items) { await C.install(cfg.runtimeDir, u, zips[u.name], () => {}); try { fs.unlinkSync(zips[u.name]); } catch { /* keep */ } }
    pendingUpdates = [];
    notify("업데이트 완료", items.map((u) => `${u.name} ${u.entry.version}`).join(", "));
  } catch (e) {
    log(`update: 실패 ${e.stack || e}`);
    updateState.error = e.message;
    notify("업데이트 실패", e.message);
  }
  await engine.start();
  await win?.loadURL(engine.url);
  updateState.applying = false; updateState.progress = null;
  updateTrayMenu("대기 중"); broadcastUpdate();
}

ipcMain.handle("update:check", async () => { const a = await checkUpdates(true); const c = await checkShellUpdate(); return { components: a, shell: c }; });
ipcMain.handle("update:apply", () => applyUpdates());
ipcMain.handle("update:applyShell", () => installShellUpdate());
ipcMain.handle("update:state", () => broadcastUpdate());
ipcMain.handle("shell:openLogs", () => shell.openPath(app.getPath("userData")));
ipcMain.handle("shell:pickVideos", async () => {
  const r = await dialog.showOpenDialog(win, { title: "영상 선택", properties: ["openFile", "multiSelections"],
    filters: [{ name: "영상", extensions: ["mp4", "mkv", "mov", "m4v", "ts", "flv", "webm"] }, { name: "모든 파일", extensions: ["*"] }] });
  return r.canceled ? [] : r.filePaths;
});
ipcMain.handle("shell:openPath", (_e, p) => (typeof p === "string" && p ? shell.openPath(p) : undefined));
ipcMain.handle("shell:info", () => {
  const cfg = engine?.cfg || {};
  const v = cfg.runtimeDir ? (C.readLocalVersion(cfg.runtimeDir) || {}) : {};
  return { mode: cfg.mode || "-", runtimeDir: cfg.runtimeDir || null, dataRoot: cfg.dataRoot || null, logDir: app.getPath("userData"),
           updateUrl: updateUrl(), isPrivate: RELEASE.isPrivate, hasToken: !!C.githubToken(), shellVersion: app.getVersion(),
           versions: { engine: v.engine_version || null, components: v.component_versions || {} }, packaged: app.isPackaged };
});

// ---------- OBS 실행 감지 → 라이브 시작 제안 (승인 모드: 알림만, 자동 시작 없음) ----------
let liveActive = false, obsSeen = false, obsTimer = null;
function obsRunning(cb) {
  const { execFile } = require("node:child_process");
  execFile("tasklist", ["/FI", "IMAGENAME eq obs64.exe", "/NH"], { windowsHide: true }, (err, out) => cb(!err && /obs64\.exe/i.test(String(out))));
}
function startObsWatch() {
  if (obsTimer || process.platform !== "win32") return;
  const tick = () => obsRunning((running) => {
    if (running && !obsSeen && !liveActive) {
      const n = new Notification({ title: "OBS 가 켜졌습니다", body: "라이브 탭에서 득템 배너 감지를 시작할까요? (알림을 누르면 엽니다)", icon: path.join(ASSETS, "icon.png") });
      n.on("click", () => { showWindow(); win?.webContents.executeJavaScript("location.hash='#live'").catch(() => {}); });
      try { n.show(); } catch { /* ignore */ }
      log("obs: 감지 → 라이브 시작 제안");
    }
    obsSeen = running;
  });
  tick(); obsTimer = setInterval(tick, 30_000);
}

// ---------- 수명 ----------
async function boot() {
  logStream = fs.createWriteStream(path.join(app.getPath("userData"), "shell.log"), { flags: "a" });
  log(`shell: start electron ${process.versions.electron} node ${process.versions.node} packaged=${app.isPackaged} smoke=${SMOKE}`);
  createWindow();
  createTray();
  engine = new Engine(app, log);
  log(`engine: mode=${engine.cfg.mode} runtime=${engine.cfg.runtimeDir || "-"} data=${engine.cfg.dataRoot || "-"} update=${updateUrl()}`);
  engine.onExit = (code) => {
    if (quitting) return;
    updateTrayMenu("엔진 종료됨");
    win?.loadURL(bootHtml("엔진이 종료됐습니다", `exit code ${code}\n로그: ${path.join(app.getPath("userData"), "shell.log")}`, false));
  };
  try {
    await ensureRuntime();
    win?.loadURL(bootHtml("엔진을 시작하는 중…", "ffmpeg · GPU · 모델을 확인합니다", true));
    const h = await engine.start();
    updateTrayMenu(`대기 중 · v${h.engine_version}`);
    await win.loadURL(engine.url);
    subscribeEvents();
    log(`shell: ui loaded ${engine.url}`);
    // 라이브 전역 단축키 (게임 창이 앞에 있어도 동작): M 북마크 · Y 최근 제안 승인 · N 최근 제안 무시. 라이브 중이 아니면 조용히 무시.
    const livePost = (path, body, onOk) => {
      const req = http.request(`${engine.url}${path}`, { method: "POST", headers: { "content-type": "application/json" } }, (res) => {
        let data = ""; res.setEncoding("utf8"); res.on("data", (c) => (data += c));
        res.on("end", () => { if (res.statusCode === 200) onOk?.(data); else log(`live ${path}: ${res.statusCode} ${data.slice(0, 120)}`); });
      });
      req.on("error", (e) => log(`live ${path}: ${e.message}`));
      req.end(JSON.stringify(body || {}));
    };
    try {
      const regs = [
        ["Control+Alt+M", () => livePost("/api/live/mark", { note: "단축키" }, () => notify("북마크", "라이브 북마크를 남겼습니다"))],
        ["Control+Alt+Y", () => livePost("/api/live/suggestions/latest/approve", {}, (d) => { try { const s = JSON.parse(d); notify("배너에 추가", `${s.head || s.text} 를 득템 배너에 넣었습니다`); } catch { /* ignore */ } })],
        ["Control+Alt+N", () => livePost("/api/live/suggestions/latest/dismiss", {}, () => notify("무시", "최근 제안을 무시했습니다"))],
      ];
      for (const [acc, fn] of regs) log(`shell: globalShortcut ${acc} ${globalShortcut.register(acc, fn) ? "ok" : "실패(다른 앱이 사용 중)"}`);
    } catch (e) { log(`shell: globalShortcut ${e.message}`); }
    startObsWatch();
    if (engine.cfg.mode === "runtime" && AUTO_UPDATE) {
      const upd = await checkUpdates();
      if (upd?.length) { await applyUpdates(); log(`auto-update: applied; VERSION=${JSON.stringify(C.readLocalVersion(engine.cfg.runtimeDir))}`); }
    }
    if (engine.cfg.mode === "runtime") {
      setupShellUpdater();
      const tick = () => { checkUpdates().catch((e) => log(`update: ${e.message}`)); checkShellUpdate(); };
      setTimeout(tick, 10_000);
      setInterval(tick, 6 * 3600_000);
    }
    if (SMOKE) {
      log("smoke: ok — 5초 뒤 종료");
      setTimeout(async () => {
        try {
          const hash = process.argv.find((a) => a.startsWith("--smoke-tab="))?.split("=")[1];
          if (hash) { await win.loadURL(`${engine.url}/#${hash}`); await new Promise((r) => setTimeout(r, 1500)); }
          const img = await win.webContents.capturePage();
          const out = path.join(app.getPath("userData"), "smoke.png");
          fs.writeFileSync(out, img.toPNG()); log(`smoke: 캡처 ${out}`);
        } catch (e) { log(`smoke: 캡처 실패 ${e.message}`); }
        quitApp();
      }, 3500);
    }
  } catch (e) {
    log(`shell: boot 실패 ${e.stack || e}`);
    updateTrayMenu("엔진 시작 실패");
    win?.loadURL(bootHtml("엔진을 시작하지 못했습니다", `${e.message}\n로그: ${path.join(app.getPath("userData"), "shell.log")}`, false));
    if (SMOKE) setTimeout(() => quitApp(1), 1000);
    else dialog.showErrorBox("clipforge", `엔진을 시작하지 못했습니다.\n${e.message}`);
  }
}

function quitApp(code = 0) {
  quitting = true;
  try { globalShortcut.unregisterAll(); } catch { /* ignore */ }
  try { ws?.close(); } catch { /* ignore */ }
  engine?.stop();
  tray?.destroy();
  app.exit(code);
}

app.whenReady().then(boot);
app.on("window-all-closed", () => { /* 트레이 상주 */ });
app.on("before-quit", () => { quitting = true; engine?.stop(); });
app.on("activate", () => showWindow());
process.on("uncaughtException", (e) => log(`uncaught: ${e.stack || e}`));
