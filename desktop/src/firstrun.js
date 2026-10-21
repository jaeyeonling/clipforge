// 첫 실행 설치 (설치본 · runtime 모드): 엔진 코드는 설치본에서 심고, 큰 구성요소는 설치 화면(pages/setup.html)에서 받는다.
//   화면 ↔ 여기: setup:ready → plan 이벤트, setup:start → 받기 · 풀기 이벤트(components.apply), setup:cancel
"use strict";
const { app, ipcMain, powerSaveBlocker } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const C = require("./components");
const RELEASE = require("./release.config");
const flags = require("./flags");
const state = require("./state");
const { log } = require("./log");
const { notify, showSetupPage, showWindow } = require("./window");
const { updateTrayMenu } = require("./tray");
const { updateUrl } = require("./updates");
const { quitApp } = require("./lifecycle");

const REQUIRED = ["python-base", "ffmpeg", "whisper"];

function sendSetup(ev) {
  state.win?.webContents.send("setup:event", ev);
}

/** 받을 폴더가 있는 디스크의 남은 공간. 모르면 null (확인 없이 진행). */
function freeBytes(dir) {
  try {
    fs.mkdirSync(dir, { recursive: true });
    const st = fs.statfsSync(dir);
    return st.bavail * st.bsize;
  } catch {
    return null;
  }
}

function hasNvidia() {
  try {
    require("node:child_process").execFileSync("nvidia-smi", ["-L"], { stdio: "ignore", windowsHide: true });
    return true;
  } catch {
    return false;
  }
}

/** 설치본이면 런타임을 갖춘다: 엔진 코드를 심고, 빠진 구성요소가 있으면 설치 화면을 띄워 끝날 때까지 기다린다. */
async function ensureRuntime() {
  const cfg = state.engine.cfg;
  if (cfg.mode !== "runtime") return;
  fs.mkdirSync(cfg.runtimeDir, { recursive: true });
  if (!C.present(cfg.runtimeDir, "engine_code")) {
    const ok = await C.seedFromResources(cfg.runtimeDir, cfg.seedDir);
    log(`runtime: engine code seed ${ok ? "ok" : "없음"} ← ${cfg.seedDir}`);
  }
  const need = REQUIRED.filter((n) => !C.present(cfg.runtimeDir, n));
  if (!need.length) return;
  log(`runtime: 구성요소 필요 ${need.join(",")} → 설치 화면`);
  await runSetup(cfg);
}

function runSetup(cfg) {
  return new Promise((resolve, reject) => {
    let manifest = null,
      abort = null;

    const sendPlan = async () => {
      try {
        manifest = await C.fetchManifest(updateUrl());
        const gpu = hasNvidia();
        const items = C.plan(cfg.runtimeDir, manifest, {})
          .filter((it) => it.kind === "component")
          .map((it) => ({
            name: it.name,
            label: it.entry.label || it.name,
            size: it.entry.size,
            optional: !!it.entry.optional,
            reason: it.reason,
            selected: it.entry.optional ? gpu : true,
            have: C.savedBytes(cfg.downloads, it.entry),
          }));
        log(`setup: 받을 구성요소 ${items.length}개 (${items.map((it) => it.name).join(", ")})`);
        sendSetup({
          type: "plan",
          items,
          free: freeBytes(cfg.downloads),
          desc: gpu
            ? "NVIDIA GPU 가 감지되어 GPU 가속을 함께 받아요."
            : "NVIDIA GPU 가 없어 GPU 가속은 선택에서 뺐어요 (CPU 로도 동작, 전사만 느려요).",
        });
      } catch (e) {
        log(`setup: manifest 실패 ${e.message}`);
        const tokenHint =
          RELEASE.isPrivate && !C.githubToken()
            ? "\n비공개 저장소라 토큰이 필요해요: %LOCALAPPDATA%\\clipforge\\github-token.txt 에 읽기 전용 토큰을 넣고 다시 시도하세요."
            : "";
        sendSetup({
          type: "plan",
          items: [],
          title: "구성요소 목록을 받지 못했어요",
          desc: `${C.friendlyError(e)}\n서버: ${updateUrl()}${tokenHint}`,
        });
      }
    };

    const startInstall = async (opts) => {
      if (!manifest) {
        await sendPlan();
        if (!manifest) return;
      }
      const items = C.plan(cfg.runtimeDir, manifest, { wantOptional: opts.optional || {} }).filter(
        (it) => it.kind === "component",
      );
      abort = new AbortController();
      updateTrayMenu("구성요소 내려받는 중");
      // 긴 다운로드 중에 PC 가 잠들면 연결이 끊기므로 설치하는 동안만 절전을 막는다
      const awake = powerSaveBlocker.start("prevent-app-suspension");
      try {
        const prog = new Map(); // 항목별 받은 바이트 → 트레이 · 작업 표시줄에는 전체 비율
        const totalBytes = items.reduce((a, it) => a + (it.entry.size || 0), 0) || 1;
        await C.apply(cfg.runtimeDir, items, {
          downloadDir: cfg.downloads,
          signal: abort.signal,
          onEvent: (ev) => {
            sendSetup(ev);
            if (ev.type === "download" && !ev.retry) {
              prog.set(ev.name, ev.done);
              const frac = Math.min(1, [...prog.values()].reduce((a, b) => a + b, 0) / totalBytes);
              updateTrayMenu(`내려받는 중 ${Math.round(100 * frac)}%`);
              state.win?.setProgressBar(frac); // 다른 창을 보고 있어도 작업 표시줄에서 보이게
            }
            if (ev.type === "install") updateTrayMenu(`설치 중 ${ev.name}`);
          },
        });
        log("setup: 완료");
        state.win?.setProgressBar(-1);
        if (!state.win?.isFocused()) {
          notify("준비가 끝났어요", "편집본을 넣으면 쇼츠 초안을 만들어요.");
          state.win?.flashFrame(true);
        }
        resolve();
      } catch (e) {
        log(`setup: 실패 ${e.stack || e}`);
        state.win?.setProgressBar(1, { mode: "error" });
        sendSetup({
          type: "error",
          name: items.find((it) => !C.present(cfg.runtimeDir, it.name))?.name || items[0]?.name,
          message: C.friendlyError(e),
        });
        if (flags.SMOKE) reject(e);
      } finally {
        powerSaveBlocker.stop(awake);
      }
    };

    for (const ch of ["setup:ready", "setup:start", "setup:cancel"]) ipcMain.removeHandler(ch);
    ipcMain.handle("setup:ready", async () => {
      await sendPlan();
      if (flags.AUTO_SETUP && manifest) startInstall({ optional: { cuda: hasNvidia() } });
    });
    ipcMain.handle("setup:start", (_e, opts) => startInstall(opts || {}));
    ipcMain.handle("setup:cancel", () => abort?.abort());

    showSetupPage();
    showWindow();
    if (flags.SMOKE_SETUP) {
      // 화면 점검: 설치 화면이 그려진 뒤 캡처하고 종료
      setTimeout(async () => {
        try {
          const img = await state.win.webContents.capturePage();
          const out = path.join(app.getPath("userData"), "smoke-setup.png");
          fs.writeFileSync(out, img.toPNG());
          log(`smoke-setup: 캡처 ${out}`);
        } catch (e) {
          log(`smoke-setup: 캡처 실패 ${e.message}`);
        }
        quitApp();
      }, 4000);
    }
  });
}

module.exports = { ensureRuntime };
