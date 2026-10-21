// 트레이: 열기 · 상태 한 줄 · 업데이트 적용 · 로그 폴더 · 브라우저에서 열기 · 종료.
// 동작(업데이트 적용 · 종료 등)은 main.js 가 createTray 로 넘겨준다 — 모듈끼리 서로 부르지 않게.
"use strict";
const { app, Menu, Tray, nativeImage, shell } = require("electron");
const path = require("node:path");
const state = require("./state");
const { log } = require("./log");
const { ASSETS } = require("./window");

let actions = {
  open: () => {},
  pending: () => ({ components: [], shell: null }),
  applyUpdates: () => {},
  installShellUpdate: () => {},
  checkUpdates: () => {},
  quit: () => {},
};
let status = "";

function createTray(a) {
  actions = { ...actions, ...a };
  state.tray = new Tray(nativeImage.createFromPath(path.join(ASSETS, "tray.png")));
  state.tray.setToolTip("clipforge");
  updateTrayMenu("엔진 준비 중");
  state.tray.on("click", () => actions.open());
}

/** status 가 null 이면 상태 줄은 그대로 두고 메뉴만 다시 그린다 (업데이트 항목이 바뀌었을 때). */
function updateTrayMenu(next) {
  if (next != null) status = next;
  if (!state.tray) return;
  const { components, shell: shellUpdate } = actions.pending();
  const upd = [];
  if (components.length)
    upd.push({
      label: `업데이트 적용 (${components.map((u) => u.name).join(", ")})`,
      enabled: !state.jobRunning,
      click: () => Promise.resolve(actions.applyUpdates()).catch((e) => log(`update: ${e.message}`)),
    });
  if (shellUpdate)
    upd.push({
      label: `앱 ${shellUpdate.version} 설치하고 다시 시작`,
      enabled: !state.jobRunning,
      click: () => actions.installShellUpdate(),
    });
  state.tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "clipforge 열기", click: () => actions.open() },
      { label: status, enabled: false },
      ...upd,
      {
        label: "업데이트 확인",
        click: () => Promise.resolve(actions.checkUpdates()).catch((e) => log(`update: ${e.message}`)),
      },
      { type: "separator" },
      { label: "로그 폴더 열기", click: () => shell.openPath(app.getPath("userData")) },
      { label: "브라우저에서 열기", click: () => state.engine?.port && shell.openExternal(state.engine.url) },
      { type: "separator" },
      { label: "종료", click: () => actions.quit() },
    ]),
  );
}

module.exports = { createTray, updateTrayMenu };
