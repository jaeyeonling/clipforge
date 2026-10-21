// 첫 실행 설치 화면의 상태와 계산: 이벤트(plan · start · download · install · done · error)를 받아 상태를 바꾸고,
// 그릴 내용(view)을 돌려준다. 화면(setup.js)은 그리기만 하고, 계산은 여기서 테스트한다 (test/setup-model.test.js).
// 브라우저에서는 window.SetupModel, Node 에서는 require 로 쓴다.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SetupModel = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const human = (n) =>
    n >= 1e9 ? (n / 1e9).toFixed(1) + "GB" : n >= 1e6 ? Math.round(n / 1e6) + "MB" : Math.round(n / 1e3) + "KB";

  /** 남은 시간: 분 단위로 먼저 반올림해 "1시간 60분" 같은 표시가 나오지 않게 한다. */
  function fmtDur(s) {
    if (s < 60) return Math.max(1, Math.round(s)) + "초";
    const m = Math.round(s / 60);
    if (m < 60) return m + "분";
    const h = Math.floor(m / 60),
      r = m % 60;
    return r ? `${h}시간 ${r}분` : `${h}시간`;
  }

  /** 최근 windowMs 동안의 속도(바이트/초). 이어 받은 양이나 처음 몇 초의 느린 연결에 휘둘리지 않게. */
  function rateMeter(windowMs = 20000) {
    const samples = [];
    return {
      add(done, now) {
        samples.push([now, done]);
        while (samples.length > 2 && now - samples[0][0] > windowMs) samples.shift();
        const [t, d] = samples[0],
          dt = (now - t) / 1000;
        return dt > 2 ? Math.max(0, (done - d) / dt) : 0;
      },
      reset() {
        samples.length = 0;
      },
    };
  }

  const NEED_FACTOR = 2.2; // 받을 zip + 풀린 파일. 수십 분 받은 뒤 공간이 모자라 실패하지 않게 넉넉히 잡는다
  const WAIT_MS = 8000; // 몇 초째 진척이 없으면 "서버 응답을 기다리는 중" 으로 알린다

  function idleStatus(it) {
    if (it.have >= it.size) return "받아 둠 · 풀기만 하면 돼요";
    if (it.have) return human(it.have) + " 받아 둠 · 이어 받아요";
    return it.reason === "update" ? "업데이트" : "새로 설치";
  }

  function createSetupState() {
    const meter = rateMeter();
    const s = { items: [], free: null, running: false, failed: false, title: null, desc: null };

    function apply(ev, now) {
      if (ev.type === "plan") {
        s.items = ev.items.map((x) => ({ ...x, pct: x.have ? Math.round((100 * x.have) / x.size) : 0 }));
        s.free = ev.free ?? null;
        if (ev.title) s.title = ev.title;
        if (ev.desc) s.desc = ev.desc;
        return;
      }
      const it = s.items.find((x) => x.name === ev.name);
      if (!it) return;
      if (ev.type === "start") {
        s.running = true;
        s.failed = false;
        it.status = it.have ? "이어 받는 중…" : "받는 중…";
        it.tone = null;
        it.pct = it.have ? Math.round((100 * it.have) / it.size) : 0;
        it.done = it.have || 0;
      } else if (ev.type === "download" && ev.retry) {
        it.retrying = true;
        it.status =
          (ev.reason === "STALL" ? "응답이 멈춰 " : "연결이 끊겨 ") +
          `${Math.round(ev.waitMs / 1000)}초 뒤 이어 받아요 (${ev.retry}/${ev.of})`;
      } else if (ev.type === "download") {
        it.retrying = false;
        it.seen = now;
        it.done = ev.done;
        it.pct = ev.total ? Math.round((100 * ev.done) / ev.total) : 0;
        it.status = ev.cached ? "이미 받음" : `받는 중 ${human(ev.done)} / ${human(ev.total)}`;
      } else if (ev.type === "downloaded") {
        it.done = it.size;
        it.pct = 100;
        it.status = "받았어요 · 설치 차례 기다리는 중";
      } else if (ev.type === "install") {
        it.done = it.size;
        it.pct = 100;
        it.status = ev.phase === "extract" ? "푸는 중" + (ev.pct != null ? ` ${ev.pct}%` : "") : "교체 중";
      } else if (ev.type === "done") {
        it.done = it.size;
        it.pct = 100;
        it.finished = true;
        it.status = "완료";
        it.tone = "ok";
      } else if (ev.type === "error") {
        s.running = false;
        s.failed = true;
        meter.reset();
        it.retrying = false;
        it.status = ev.message;
        it.tone = "bad";
      }
    }

    function select(name, on) {
      const it = s.items.find((x) => x.name === name);
      if (it && it.optional && !s.running) it.selected = on;
    }

    function begin() {
      s.running = true;
      s.failed = false;
    }

    function view(now) {
      const sel = s.items.filter((x) => x.selected);
      const total = sel.reduce((a, x) => a + (x.size || 0), 0);
      const have = sel.reduce((a, x) => a + (x.have || 0), 0);
      const need = Math.round(total * NEED_FACTOR) - have;
      const short = s.free != null && s.free < need;
      const room = s.free != null ? ` · 필요한 공간 약 ${human(need)} / 남은 공간 ${human(s.free)}` : "";

      const rows = s.items.map((it) => {
        let status = it.status || idleStatus(it);
        if (s.running && it.seen && !it.retrying && it.pct < 100 && now - it.seen > WAIT_MS)
          status = `서버 응답을 기다리는 중… (${human(it.done || 0)} 받음)`;
        return {
          name: it.name,
          label: it.label,
          size: human(it.size || 0),
          pct: it.pct || 0,
          status,
          tone: it.tone || null,
          selected: !!it.selected,
          editable: !!it.optional && !s.running,
        };
      });

      let hint;
      if (s.running) hint = { text: "받는 동안 창을 닫아도 트레이에서 계속 받아요. 끊겨도 받은 데서부터 이어 받아요." };
      else if (short) hint = { text: `디스크 공간이 모자라요${room}. 공간을 비운 뒤 다시 열어 주세요.`, tone: "bad" };
      else
        hint = {
          text:
            `받을 양 ${human(Math.max(0, total - have))}` +
            (have ? ` (${human(have)} 받아 둠)` : "") +
            room +
            " — 회선에 따라 수 분~수십 분 걸려요.",
        };

      let overall = null;
      if (s.running && total) {
        const done = sel.reduce((a, x) => a + (x.done || (x.pct === 100 ? x.size : 0) || 0), 0);
        const pct = Math.min(100, Math.round((100 * done) / total));
        const rate = meter.add(done, now);
        const left = rate > 0 ? (total - done) / rate : 0;
        const fin = sel.filter((x) => x.finished).length;
        const waiting = sel.some((x) => x.retrying);
        const text =
          fin === sel.length
            ? "다 됐어요. 엔진을 시작해요"
            : (waiting ? "연결을 다시 잡는 중… · " : "") +
              (pct >= 100
                ? "받았어요. 푸는 중…"
                : left > 0
                  ? `약 ${fmtDur(left)} 남았어요 · ${human(rate)}/s`
                  : "속도 재는 중…") +
              ` · ${fin}/${sel.length} 완료`;
        overall = { pct, text };
      }

      return {
        title: s.title,
        desc: s.desc,
        rows,
        hint,
        overall,
        start: {
          label: s.running ? "설치하는 중…" : have ? "이어 받기" : "설치 시작",
          disabled: s.running || !sel.length || short,
        },
        retry: s.failed,
        optional: Object.fromEntries(s.items.filter((x) => x.optional).map((x) => [x.name, !!x.selected])),
      };
    }

    return {
      apply,
      select,
      begin,
      view,
      get running() {
        return s.running;
      },
    };
  }

  return { human, fmtDur, rateMeter, idleStatus, createSetupState };
});
