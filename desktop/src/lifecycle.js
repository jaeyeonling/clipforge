// 앱 종료: 전역 단축키 해제 → 엔진 구독 닫기 → 엔진 정지 → 트레이 제거.
"use strict";
const { app, globalShortcut } = require("electron");
const state = require("./state");

function quitApp(code = 0) {
  state.quitting = true;
  try {
    globalShortcut.unregisterAll();
  } catch {
    /* 이미 해제됨 */
  }
  try {
    state.ws?.close();
  } catch {
    /* 이미 닫힘 */
  }
  state.engine?.stop();
  state.tray?.destroy();
  app.exit(code);
}

module.exports = { quitApp };
