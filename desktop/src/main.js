// clipforge 데스크톱 껍데기 (Electron) — 시작과 연결만 한다. 기능은 모듈에:
//   window   창 · 앱 화면(부팅 · 설치) · 알림 · 보안 기본값      tray      트레이 메뉴
//   firstrun 첫 실행 설치 (설치본)                              updates   앱 내 업데이트(층 A·B) · 껍데기 업데이트(층 C)
//   events   엔진 /ws → 트레이 · 알림 · 라이브 단축키            live      전역 단축키 · OBS 감지
//   ipc      화면이 부르는 shell.* 기능                         engine    엔진 자식 프로세스
//
//   설치본 모드(runtime): %LOCALAPPDATA%\clipforge\runtime 에 엔진 코드(동봉) + 구성요소(첫 실행 때 받음)를 두고 거기서 엔진을 띄운다.
//   개발 모드(venv/dist): 저장소의 파이썬으로 바로 띄운다. 창을 닫으면 트레이로.
//   점검 플래그는 flags.js (--smoke · --smoke-setup · --auto-setup · --fake-update · --auto-update).
"use strict";
const { app, dialog } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { Engine } = require("./engine");
const C = require("./components");
const flags = require("./flags");
const state = require("./state");
const { log, openLog } = require("./log");
const win = require("./window");
const { createTray, updateTrayMenu } = require("./tray");
const updates = require("./updates");
const { ensureRuntime } = require("./firstrun");
const { subscribeEvents } = require("./events");
const live = require("./live");
const { registerShellIpc } = require("./ipc");
const { quitApp } = require("./lifecycle");

if (!app.requestSingleInstanceLock()) app.quit();
app.on("second-instance", () => win.showWindow());
app.setAppUserModelId("kr.clipforge.app");
win.registerPageScheme();
updates.registerUpdateIpc();
registerShellIpc();

const logFile = () => path.join(app.getPath("userData"), "shell.log");

async function smokeCapture() {
  log("smoke: ok — 곧 캡처하고 종료");
  await new Promise((r) => setTimeout(r, 3500));
  try {
    if (flags.SMOKE_TAB) {
      await state.win.loadURL(`${state.engine.url}/#${flags.SMOKE_TAB}`);
      await new Promise((r) => setTimeout(r, 1500));
    }
    const img = await state.win.webContents.capturePage();
    const out = path.join(app.getPath("userData"), "smoke.png");
    fs.writeFileSync(out, img.toPNG());
    log(`smoke: 캡처 ${out}`);
  } catch (e) {
    log(`smoke: 캡처 실패 ${e.message}`);
  }
  quitApp();
}

async function boot() {
  openLog(logFile());
  log(
    `shell: start electron ${process.versions.electron} node ${process.versions.node} packaged=${app.isPackaged} smoke=${flags.SMOKE}`,
  );
  win.installSecurity();
  win.createWindow();
  createTray({
    open: () => win.showWindow(),
    pending: () => updates.pendingSummary(),
    applyUpdates: () => updates.applyUpdates(),
    installShellUpdate: () => updates.installShellUpdate(),
    checkUpdates: () => updates.checkUpdates(true),
    quit: () => quitApp(),
  });
  const engine = new Engine(app, log);
  state.engine = engine;
  log(
    `engine: mode=${engine.cfg.mode} runtime=${engine.cfg.runtimeDir || "-"} data=${engine.cfg.dataRoot || "-"} update=${updates.updateUrl()}`,
  );
  engine.onExit = (code) => {
    live.setLiveShortcuts(false);
    if (state.quitting) return;
    updateTrayMenu("엔진 종료됨");
    win.showBoot("엔진이 종료됐어요", `exit code ${code}\n로그: ${logFile()}`);
  };
  try {
    await ensureRuntime();
    win.showBoot("엔진을 시작하는 중…", "ffmpeg · GPU · 모델을 확인해요", true);
    const h = await engine.start();
    updateTrayMenu(`대기 중 · v${h.engine_version}`);
    await state.win.loadURL(engine.url);
    subscribeEvents();
    log(`shell: ui loaded ${engine.url}`);
    live.registerLiveKeys(engine.url); // 라이브를 시작할 때만 잡는다 (events.js)
    live.startObsWatch();
    if (engine.cfg.mode === "runtime") {
      if (flags.AUTO_UPDATE) {
        const upd = await updates.checkUpdates();
        if (upd?.length) {
          await updates.applyUpdates();
          log(`auto-update: applied; VERSION=${JSON.stringify(C.readLocalVersion(engine.cfg.runtimeDir))}`);
        }
      }
      updates.scheduleChecks();
    }
    if (flags.FAKE_UPDATE) updates.fakePending();
    if (flags.SMOKE) smokeCapture();
  } catch (e) {
    log(`shell: boot 실패 ${e.stack || e}`);
    updateTrayMenu("엔진 시작 실패");
    win.showBoot("엔진을 시작하지 못했어요", `${e.message}\n로그: ${logFile()}`);
    if (flags.SMOKE) setTimeout(() => quitApp(1), 1000);
    else dialog.showErrorBox("clipforge", `엔진을 시작하지 못했어요.\n${e.message}`);
  }
}

app.whenReady().then(boot);
app.on("window-all-closed", () => {
  /* 트레이 상주 */
});
app.on("before-quit", () => {
  state.quitting = true;
  state.engine?.stop();
});
app.on("activate", () => win.showWindow());
process.on("uncaughtException", (e) => log(`uncaught: ${e.stack || e}`));
