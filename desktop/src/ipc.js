// 화면이 부르는 껍데기 기능 (preload.js 의 shell.*): 영상 고르기 · 폴더 열기 · 정보.
"use strict";
const { app, dialog, ipcMain, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const C = require("./components");
const RELEASE = require("./release.config");
const state = require("./state");
const { log } = require("./log");
const { updateUrl } = require("./updates");

// 화면이 여는 것은 폴더와 결과물(초안 · XML · 자막 · 로그)뿐이다. 실행 파일 등 다른 것은 열지 않는다 —
// 화면에 스크립트가 끼어들어도 이 통로로 프로그램을 실행할 수 없게.
const OPENABLE = new Set([
  ".mp4",
  ".mkv",
  ".mov",
  ".m4v",
  ".webm",
  ".xml",
  ".srt",
  ".vtt",
  ".txt",
  ".csv",
  ".json",
  ".png",
  ".jpg",
  ".log",
  ".zip",
]);

/** 열어도 되는 경로인가: 있는 폴더이거나, 허용한 확장자의 있는 파일. */
function isSafeToOpen(p, stat = fs.statSync) {
  if (typeof p !== "string" || !p || !path.isAbsolute(p)) return false;
  let st;
  try {
    st = stat(p);
  } catch {
    return false;
  }
  return st.isDirectory() || (st.isFile() && OPENABLE.has(path.extname(p).toLowerCase()));
}

function registerShellIpc() {
  ipcMain.handle("shell:openLogs", () => shell.openPath(app.getPath("userData")));
  ipcMain.handle("shell:pickVideos", async () => {
    const r = await dialog.showOpenDialog(state.win, {
      title: "영상 선택",
      properties: ["openFile", "multiSelections"],
      filters: [
        { name: "영상", extensions: ["mp4", "mkv", "mov", "m4v", "ts", "flv", "webm"] },
        { name: "모든 파일", extensions: ["*"] },
      ],
    });
    return r.canceled ? [] : r.filePaths;
  });
  ipcMain.handle("shell:openPath", (_e, p) => {
    if (isSafeToOpen(p)) return shell.openPath(p);
    log(`shell: 열지 않음 ${String(p).slice(0, 200)}`);
    return undefined;
  });
  ipcMain.handle("shell:info", () => {
    const cfg = state.engine?.cfg || {};
    const v = cfg.runtimeDir ? C.readLocalVersion(cfg.runtimeDir) || {} : {};
    return {
      mode: cfg.mode || "-",
      runtimeDir: cfg.runtimeDir || null,
      dataRoot: cfg.dataRoot || null,
      logDir: app.getPath("userData"),
      updateUrl: updateUrl(),
      isPrivate: RELEASE.isPrivate,
      hasToken: !!C.githubToken(),
      shellVersion: app.getVersion(),
      versions: { engine: v.engine_version || null, components: v.component_versions || {} },
      packaged: app.isPackaged,
    };
  });
}

module.exports = { registerShellIpc, isSafeToOpen };
