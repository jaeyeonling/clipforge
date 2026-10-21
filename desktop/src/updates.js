// 업데이트 (docs/ARCHITECTURE.md · 배포와 업데이트)
//   층 A·B (엔진 코드 · 런타임 구성요소): latest.json 을 보고 바뀐 것만 받아 엔진을 멈추고 교체 → 다시 시작
//   층 C (껍데기): electron-updater 가 GitHub Releases 의 latest.yml 을 보고 받아 두고, 다음 종료 때 설치
"use strict";
const { app, ipcMain } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const C = require("./components");
const RELEASE = require("./release.config");
const state = require("./state");
const { log } = require("./log");
const { notify, showBoot } = require("./window");
const { updateTrayMenu } = require("./tray");

let pending = []; // plan() 결과 중 아직 적용 안 한 것 (층 A·B)
let shellUpdate = null; // electron-updater 가 받아 둔 껍데기 새 버전 {version}
let autoUpdater = null;
const updateState = { checking: false, applying: false, lastCheck: null, error: null, progress: null };

/** 업데이트 서버: 환경변수 → %LOCALAPPDATA%\clipforge\update-url.txt (USB · 오프라인 설치) → GitHub Releases */
function updateUrl() {
  if (process.env.CLIPFORGE_UPDATE_URL) return process.env.CLIPFORGE_UPDATE_URL;
  try {
    const t = fs.readFileSync(path.join(process.env.LOCALAPPDATA || "", "clipforge", "update-url.txt"), "utf8").trim();
    if (t) return t;
  } catch {
    /* 없으면 기본 */
  }
  return RELEASE.updateUrl;
}

/** 트레이 메뉴가 그릴 대기 항목 */
function pendingSummary() {
  return { components: pending, shell: shellUpdate };
}

/** 화면(설정 탭 · 업데이트 시트)에 지금 상태를 보낸다 */
function broadcastUpdate() {
  const st = {
    ...updateState,
    shell: shellUpdate,
    pending: pending.map((u) => ({
      name: u.name,
      version: u.entry.version,
      size: u.entry.size || 0,
      reason: u.reason,
      notes: u.entry.notes || "",
    })),
  };
  try {
    state.win?.webContents.send("update:state", st);
  } catch {
    /* 창 없음 */
  }
  return st;
}

// ---------- 층 C: 껍데기 ----------
function setupShellUpdater() {
  if (!app.isPackaged) {
    log("shell-update: 개발 모드 — 건너뜀");
    return;
  }
  try {
    ({ autoUpdater } = require("electron-updater"));
  } catch (e) {
    log(`shell-update: electron-updater 없음 ${e.message}`);
    return;
  }
  autoUpdater.logger = {
    info: (m) => log(`shell-update: ${m}`),
    warn: (m) => log(`shell-update: ${m}`),
    error: (m) => log(`shell-update: ${m}`),
    debug: () => {},
  };
  autoUpdater.autoDownload = true; // 껍데기는 작으니 조용히 받아 둔다
  autoUpdater.autoInstallOnAppQuit = true; // 종료 때 설치. 강제 재시작은 하지 않는다 (방송 방해 금지)
  autoUpdater.allowDowngrade = false;
  // 토큰이 있으면 비공개 피드, 없으면 공개 피드(app-update.yml)
  const token = C.githubToken();
  if (token)
    autoUpdater.setFeedURL({ provider: "github", owner: RELEASE.owner, repo: RELEASE.repo, private: true, token });
  else if (RELEASE.isPrivate)
    log("shell-update: 토큰이 없어 공개 피드로 확인해요 (저장소가 비공개면 실패하고 다음 확인 때 다시 시도)");
  autoUpdater.on("update-available", (info) => log(`shell-update: available ${info.version}`));
  autoUpdater.on("update-not-available", () => log("shell-update: 최신"));
  autoUpdater.on("error", (e) => log(`shell-update: error ${e?.message || e}`));
  autoUpdater.on("update-downloaded", (info) => {
    shellUpdate = { version: info.version };
    updateTrayMenu(null);
    broadcastUpdate();
    notify(
      `앱 ${info.version} 준비됨`,
      "다음에 종료할 때 자동으로 설치돼요. 지금 설치하려면 트레이 메뉴에서 선택하세요.",
    );
  });
}

async function checkShellUpdate() {
  if (!autoUpdater) return null;
  try {
    const r = await autoUpdater.checkForUpdates();
    return r?.updateInfo?.version || null;
  } catch (e) {
    log(`shell-update: check 실패 ${e.message}`);
    return null;
  }
}

function installShellUpdate() {
  if (!autoUpdater || !shellUpdate || state.jobRunning) return;
  state.quitting = true;
  try {
    state.ws?.close();
  } catch {
    /* 이미 닫힘 */
  }
  state.engine?.stop();
  autoUpdater.quitAndInstall(false, true);
}

// ---------- 층 A·B: 엔진 코드 · 런타임 구성요소 ----------
async function checkUpdates(interactive = false) {
  const cfg = state.engine?.cfg;
  if (!cfg || cfg.mode !== "runtime") {
    if (interactive) notify("업데이트", "개발 모드에서는 업데이트를 확인하지 않아요.");
    updateState.error = "dev";
    broadcastUpdate();
    return [];
  }
  updateState.checking = true;
  updateState.error = null;
  broadcastUpdate();
  let manifest;
  try {
    manifest = await C.fetchManifest(updateUrl());
  } catch (e) {
    updateState.checking = false;
    updateState.error = e.message;
    updateState.lastCheck = Date.now();
    broadcastUpdate();
    throw e;
  }
  const local = C.readLocalVersion(cfg.runtimeDir) || {};
  // 설치된 것만 갱신한다 (GPU 가속을 안 받았으면 계속 안 받는다)
  const want = Object.fromEntries(Object.keys(manifest.components || {}).map((n) => [n, C.present(cfg.runtimeDir, n)]));
  pending = C.plan(cfg.runtimeDir, manifest, { wantOptional: want }).filter((it) => it.reason === "update");
  log(
    `update: local ${local.engine_version} → 매니페스트 ${manifest.engine_code?.version}; 대기 ${pending.map((u) => `${u.name}@${u.entry.version}`).join(",") || "없음"}`,
  );
  updateState.checking = false;
  updateState.lastCheck = Date.now();
  updateTrayMenu(null);
  broadcastUpdate();
  if (pending.length) {
    const size = pending.reduce((a, u) => a + (u.entry.size || 0), 0);
    notify(
      "업데이트 있음",
      `${pending.map((u) => u.name).join(", ")} (${(size / 1e6).toFixed(0)}MB). 트레이 메뉴에서 적용하세요.${state.jobRunning ? " 작업이 끝난 뒤 적용돼요." : ""}`,
    );
  } else if (interactive) notify("업데이트", "최신 상태예요.");
  return pending;
}

/** 받기 → 엔진 멈춤 → 교체 → 다시 시작. 받는 동안에는 엔진이 떠 있어 화면이 진행률을 보여준다. */
async function applyUpdates() {
  if (!pending.length || state.jobRunning) return;
  const engine = state.engine;
  const cfg = engine.cfg;
  const items = pending.slice();
  updateTrayMenu("업데이트 적용 중");
  updateState.applying = true;
  updateState.error = null;
  broadcastUpdate();
  const zips = {};
  try {
    const prog = new Map(); // 여러 개를 동시에 받고 진행률은 합쳐서
    const total = items.reduce((a, u) => a + (u.entry.size || 0), 0);
    await Promise.all(
      items.map(async (u) => {
        // 여러 조각(예: PyPI 의 GPU 가속 휠)이어도 같은 함수로 받는다
        zips[u.name] = await C.downloadItem(u.entry, cfg.downloads, (pr) => {
          if (pr.done == null) return; // 재시도 대기 알림
          prog.set(u.name, pr.done);
          updateState.progress = {
            name: items.length > 1 ? `${items.length}개` : u.name,
            done: [...prog.values()].reduce((a, b) => a + b, 0),
            total,
          };
          broadcastUpdate();
        });
      }),
    );
  } catch (e) {
    log(`update: 다운로드 실패 ${e.stack || e}`);
    updateState.applying = false;
    updateState.progress = null;
    updateState.error = C.friendlyError(e);
    broadcastUpdate();
    notify("업데이트 실패", C.friendlyError(e));
    updateTrayMenu("대기 중");
    return;
  }
  showBoot("업데이트를 적용하는 중…", items.map((u) => `${u.name} → ${u.entry.version}`).join("\n"), true);
  await engine.stopAndWait();
  try {
    for (const u of items) {
      await C.install(cfg.runtimeDir, u, zips[u.name], () => {});
      for (const z of zips[u.name]) {
        try {
          fs.unlinkSync(z);
        } catch {
          /* 남겨도 된다 */
        }
      }
    }
    pending = [];
    notify("업데이트 완료", items.map((u) => `${u.name} ${u.entry.version}`).join(", "));
  } catch (e) {
    log(`update: 실패 ${e.stack || e}`);
    updateState.error = e.message;
    notify("업데이트 실패", e.message);
  }
  await engine.start();
  await state.win?.loadURL(engine.url);
  updateState.applying = false;
  updateState.progress = null;
  updateTrayMenu("대기 중");
  broadcastUpdate();
}

/** 시작 10초 뒤와 6시간마다 확인 (설치본만) */
function scheduleChecks() {
  setupShellUpdater();
  const tick = () => {
    checkUpdates().catch((e) => log(`update: ${e.message}`));
    checkShellUpdate();
  };
  setTimeout(tick, 10_000);
  setInterval(tick, 6 * 3600_000);
}

/** 화면 점검용: 가짜 대기 항목 (아무것도 받지 않음) */
function fakePending() {
  pending = [
    {
      name: "engine-code",
      reason: "update",
      entry: { version: "9.9.9", size: 12_000_000, url: "about:blank", notes: "화면 점검용 가짜 항목" },
    },
  ];
  updateState.lastCheck = Date.now();
  updateTrayMenu(null);
  broadcastUpdate();
  log("fake-update: 가짜 대기 항목을 보냈어요");
}

function registerUpdateIpc() {
  ipcMain.handle("update:check", async () => {
    const components = await checkUpdates(true);
    const shell = await checkShellUpdate();
    return { components, shell };
  });
  ipcMain.handle("update:apply", () => applyUpdates());
  ipcMain.handle("update:applyShell", () => installShellUpdate());
  ipcMain.handle("update:state", () => broadcastUpdate());
}

module.exports = {
  updateUrl,
  pendingSummary,
  checkUpdates,
  applyUpdates,
  installShellUpdate,
  scheduleChecks,
  fakePending,
  registerUpdateIpc,
};
