// 모듈들이 함께 보는 상태. main.js 가 채우고, 각 모듈은 필요한 것만 읽고 쓴다.
"use strict";

module.exports = {
  win: null, // BrowserWindow
  tray: null, // Tray
  engine: null, // Engine (engine.js)
  ws: null, // 엔진 /ws 구독
  quitting: false,
  jobRunning: false, // 분석 작업이 도는 동안은 업데이트를 적용하지 않는다
  liveActive: false, // 라이브 세션이 도는 중
};
