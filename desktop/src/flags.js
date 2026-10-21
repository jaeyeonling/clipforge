// 명령줄 플래그 (자동 점검 · 화면 점검용).
"use strict";

const has = (flag) => process.argv.includes(flag);

module.exports = {
  SMOKE: has("--smoke"), // 준비 뒤 캡처하고 종료
  SMOKE_SETUP: has("--smoke-setup"), // 설치 화면을 캡처하고 종료
  SMOKE_TAB: process.argv.find((a) => a.startsWith("--smoke-tab="))?.split("=")[1] || null, // --smoke 캡처 전에 열 탭
  AUTO_SETUP: has("--auto-setup"), // 첫 실행 설치를 기본 선택으로 클릭 없이 시작
  FAKE_UPDATE: has("--fake-update"), // 가짜 업데이트가 있는 것처럼 상태를 보낸다 (아무것도 받지 않음)
  AUTO_UPDATE: has("--auto-update"), // 시작 직후 업데이트를 확인해 있으면 바로 적용
};
