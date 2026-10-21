// 첫 실행 설치 화면의 상태와 계산 (src/pages/setup-model.js).
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { fmtDur, human, rateMeter, createSetupState } = require("../src/pages/setup-model");

const GB = 1e9,
  MB = 1e6;
const PLAN = {
  type: "plan",
  free: 100 * GB,
  items: [
    { name: "python-base", label: "파이썬", size: 200 * MB, optional: false, selected: true, have: 0 },
    { name: "cuda", label: "GPU", size: 1.4 * GB, optional: true, selected: true, have: 0 },
    { name: "whisper", label: "모델", size: 1.5 * GB, optional: false, selected: true, have: 500 * MB },
  ],
};

test("남은 시간: 분 단위로 먼저 반올림해 '2시간 60분' 같은 표시가 없다", () => {
  assert.equal(fmtDur(0.4), "1초");
  assert.equal(fmtDur(45), "45초");
  assert.equal(fmtDur(3599), "1시간");
  assert.equal(fmtDur(7170), "2시간");
  assert.equal(fmtDur(5400), "1시간 30분");
  assert.equal(human(1.5 * GB), "1.5GB");
});

test("속도는 최근 20초만 본다 (이어 받은 양 · 처음의 느린 구간에 휘둘리지 않게)", () => {
  const m = rateMeter(20000);
  assert.equal(m.add(500 * MB, 0), 0, "2초 전에는 재지 않는다");
  m.add(500 * MB + 10 * MB, 5000);
  const r = m.add(500 * MB + 40 * MB, 10000);
  assert.ok(Math.abs(r - 4 * MB) < 1, `받은 양 40MB / 10초 = 4MB/s (이어 받은 500MB 는 빼고), got ${r}`);
  const later = m.add(500 * MB + 40 * MB + 200 * MB, 40000); // 20초 창 밖 표본은 버린다
  assert.ok(later > 6 * MB, `최근 속도를 따라간다, got ${later}`);
});

test("계획: 받아 둔 양, 필요한 공간, '이어 받기' 버튼", () => {
  const s = createSetupState();
  s.apply(PLAN, 0);
  const v = s.view(0);
  assert.equal(v.start.label, "이어 받기");
  assert.equal(v.start.disabled, false);
  assert.match(v.hint.text, /받을 양 2\.6GB \(500MB 받아 둠\)/);
  assert.equal(v.rows[2].status, "500MB 받아 둠 · 이어 받아요");
  assert.equal(v.rows[2].pct, 33);
  assert.equal(v.rows[1].editable, true, "선택 항목(GPU)만 끌 수 있다");
  assert.equal(v.rows[0].editable, false);
});

test("디스크 공간이 모자라면 시작하지 못하게 하고 알린다", () => {
  const s = createSetupState();
  s.apply({ ...PLAN, free: 2 * GB }, 0);
  const v = s.view(0);
  assert.equal(v.start.disabled, true);
  assert.equal(v.hint.tone, "bad");
  assert.match(v.hint.text, /디스크 공간이 모자라요/);
  s.select("cuda", false);
  assert.equal(s.view(0).optional.cuda, false, "GPU 가속을 끄면 선택이 반영된다");
});

test("받기 → 재시도 → 응답 기다림 → 완료 → 오류의 상태 문구", () => {
  const s = createSetupState();
  s.apply(PLAN, 0);
  s.begin();
  s.apply({ type: "start", name: "cuda" }, 0);
  s.apply({ type: "download", name: "cuda", done: 100 * MB, total: 1.4 * GB }, 1000);
  assert.match(s.view(1000).rows[1].status, /받는 중 100MB \/ 1\.4GB/);
  assert.match(s.view(10_000).rows[1].status, /서버 응답을 기다리는 중/, "8초 넘게 진척이 없으면");
  s.apply({ type: "download", name: "cuda", retry: 1, of: 5, waitMs: 2000, reason: "STALL" }, 11_000);
  assert.equal(s.view(11_000).rows[1].status, "응답이 멈춰 2초 뒤 이어 받아요 (1/5)");
  assert.match(s.view(11_000).overall.text, /연결을 다시 잡는 중/);
  s.apply({ type: "done", name: "cuda" }, 12_000);
  assert.equal(s.view(12_000).rows[1].tone, "ok");
  assert.match(s.view(12_000).overall.text, /1\/3 완료/);
  assert.equal(s.view(12_000).start.label, "설치하는 중…");
  s.apply({ type: "error", name: "whisper", message: "인터넷에 연결되지 않아요." }, 13_000);
  const v = s.view(13_000);
  assert.equal(v.retry, true);
  assert.equal(v.rows[2].tone, "bad");
  assert.equal(v.rows[2].status, "인터넷에 연결되지 않아요.");
});
