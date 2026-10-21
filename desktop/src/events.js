// 엔진 /ws 구독 → 트레이 상태 · OS 알림 · 라이브 단축키. 끊기면 2초 뒤 다시 붙는다.
"use strict";
const WebSocket = require("ws");
const state = require("./state");
const { log } = require("./log");
const { notify } = require("./window");
const { updateTrayMenu } = require("./tray");
const { setLiveShortcuts } = require("./live");

/** 이벤트 하나를 껍데기 상태에 반영한다. */
function handleEvent(ev) {
  if (ev.type === "started" || ev.type === "progress") {
    state.jobRunning = true;
    updateTrayMenu(`실행 중: ${ev.stage || ""} ${Math.round(ev.pct || 0)}%`);
  }
  if (ev.type === "done") {
    state.jobRunning = false;
    updateTrayMenu("대기 중");
    if (!state.win?.isFocused()) notify(ev.status === "cancelled" ? "작업 취소됨" : "작업 완료", `job ${ev.job_id}`);
  }
  if (ev.type === "error") {
    state.jobRunning = false;
    updateTrayMenu(`오류: ${ev.code}`);
    notify(`작업 오류 ${ev.code}`, `${ev.message || ""}\n${ev.hint || ""}`.trim());
  }
  // 라이브 제안: 게임 중이라 앱 창을 못 보는 사람에게 OS 알림 + 단축키 안내
  if (ev.type === "live" && ev.event) {
    const le = ev.event;
    if (le.type === "suggestion" && le.status === "pending" && !state.win?.isFocused())
      notify(`득템 제안: ${le.head || le.text} (${le.grade})`, "Ctrl+Alt+Y 배너에 추가 · Ctrl+Alt+N 무시");
    if (le.type === "started") {
      state.liveActive = true;
      setLiveShortcuts(true);
    }
    if (le.type === "stopped") {
      state.liveActive = false;
      setLiveShortcuts(false);
    }
  }
}

function subscribeEvents() {
  const url = state.engine.url.replace("http", "ws") + "/ws";
  const connect = () => {
    if (state.quitting || !state.engine?.port) return;
    const ws = new WebSocket(url);
    state.ws = ws;
    ws.on("open", () => log("ws: connected"));
    ws.on("message", (raw) => {
      let ev;
      try {
        ev = JSON.parse(String(raw));
      } catch {
        return;
      }
      handleEvent(ev);
    });
    ws.on("close", () => {
      state.ws = null;
      setLiveShortcuts(false); // 엔진과 끊기면 라이브 이벤트를 못 받으므로 단축키를 놓는다
      if (!state.quitting) setTimeout(connect, 2000);
    });
    ws.on("error", (e) => log(`ws: ${e.message}`));
  };
  connect();
}

module.exports = { subscribeEvents, handleEvent };
