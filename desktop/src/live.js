// 라이브: 전역 단축키(게임 창이 앞에 있어도 동작)와 OBS 실행 감지.
//   Ctrl+Alt+M 북마크 · Y 최근 제안 승인 · N 최근 제안 무시.
//   많은 자판에서 Ctrl+Alt 는 AltGr 이라 다른 앱 입력을 가로채지 않도록, 라이브 세션이 도는 동안에만 등록한다.
//   OBS 가 켜지면 라이브 탭을 열자고 알림만 한다 (승인 모드: 자동 시작 없음).
"use strict";
const { globalShortcut } = require("electron");
const http = require("node:http");
const state = require("./state");
const { log } = require("./log");
const { notify, showWindow } = require("./window");

let keys = []; // [[가속키, 동작]] — 엔진 주소를 알고 나서 채운다
let keysOn = false;

function setLiveShortcuts(on) {
  if (on === keysOn) return;
  keysOn = on;
  for (const [acc, fn] of keys) {
    if (on) log(`shell: globalShortcut ${acc} ${globalShortcut.register(acc, fn) ? "ok" : "실패(다른 앱이 사용 중)"}`);
    else globalShortcut.unregister(acc);
  }
}

/** 엔진 라이브 API 호출. 라이브 중이 아니면(4xx) 조용히 로그만 남긴다. */
function livePost(engineUrl, route, body, onOk) {
  const req = http.request(
    `${engineUrl}${route}`,
    { method: "POST", headers: { "content-type": "application/json" } },
    (res) => {
      let data = "";
      res.setEncoding("utf8");
      res.on("data", (c) => (data += c));
      res.on("end", () => {
        if (res.statusCode === 200) onOk?.(data);
        else log(`live ${route}: ${res.statusCode} ${data.slice(0, 120)}`);
      });
    },
  );
  req.on("error", (e) => log(`live ${route}: ${e.message}`));
  req.end(JSON.stringify(body || {}));
}

function registerLiveKeys(engineUrl) {
  keys = [
    [
      "Control+Alt+M",
      () =>
        livePost(engineUrl, "/api/live/mark", { note: "단축키" }, () => notify("북마크", "라이브 북마크를 남겼어요")),
    ],
    [
      "Control+Alt+Y",
      () =>
        livePost(engineUrl, "/api/live/suggestions/latest/approve", {}, (d) => {
          try {
            const s = JSON.parse(d);
            notify("배너에 추가", `${s.head || s.text} 를 득템 배너에 넣었어요`);
          } catch {
            /* 응답 형식이 달라도 무시 */
          }
        }),
    ],
    [
      "Control+Alt+N",
      () =>
        livePost(engineUrl, "/api/live/suggestions/latest/dismiss", {}, () => notify("무시", "최근 제안을 무시했어요")),
    ],
  ];
}

let obsSeen = false,
  obsTimer = null;

function obsRunning(cb) {
  const { execFile } = require("node:child_process");
  execFile("tasklist", ["/FI", "IMAGENAME eq obs64.exe", "/NH"], { windowsHide: true }, (err, out) =>
    cb(!err && /obs64\.exe/i.test(String(out))),
  );
}

function startObsWatch() {
  if (obsTimer || process.platform !== "win32") return;
  const tick = () =>
    obsRunning((running) => {
      if (running && !obsSeen && !state.liveActive) {
        notify("OBS 가 켜졌어요", "라이브 탭에서 득템 배너 감지를 시작할까요? (알림을 누르면 열어요)", () => {
          showWindow();
          state.win?.webContents.executeJavaScript("location.hash='#live'").catch(() => {});
        });
        log("obs: 감지 → 라이브 시작 제안");
      }
      obsSeen = running;
    });
  tick();
  obsTimer = setInterval(tick, 30_000);
}

module.exports = { setLiveShortcuts, registerLiveKeys, startObsWatch };
