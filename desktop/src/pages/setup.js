// 첫 실행 설치 화면. 상태와 계산은 setup-model.js, 여기서는 그리기와 입력만 한다.
// 서버(매니페스트) · 오류에서 온 글자는 textContent 로만 넣는다 (HTML 로 해석되지 않게).
/* global SetupModel */
"use strict";
(function () {
  const S = window.clipforgeShell.setup;
  const $ = (id) => document.getElementById(id);
  const state = SetupModel.createSetupState();

  // 기다리는 동안 보여줄 소개 — 앱이 무엇을 해 주는지, 어떻게 쓰는지
  const SLIDES = [
    [
      "이 앱이 하는 일",
      "편집본 하나 넣으면 쇼츠 초안이 나와요",
      "득템 배너·리액션·채팅이 겹치는 순간을 찾아 세로(9:16) 초안을 순위대로 만들어요.",
    ],
    [
      "쓰는 법",
      "쓸 만함 / 안 씀만 눌러 주세요",
      "판정이 6개 이상 쌓이면 다음 초안부터 순위가 취향에 맞춰져요. 키보드 K / N 으로도 돼요.",
    ],
    [
      "가져가기",
      "Premiere로 바로 가져가요",
      "세로 시퀀스 XML과, 원본 전체에 후보 트랙·마커가 붙은 리뷰 시퀀스를 만들어요. 초안 mp4 와 자막도 폴더에 있어요.",
    ],
    [
      "방송 중",
      "라이브 탭은 득템 배너를 도와줘요",
      '세트·유니크 템 이름을 읽어 "배너에 추가?" 하고 물어봐요. 승인한 것만 OBS 로 나가요. Ctrl+Alt+M 은 북마크.',
    ],
    [
      "지금 받는 것",
      "이 다운로드는 한 번뿐이에요",
      "파이썬 런타임·FFmpeg·음성 인식 모델(·GPU 가속)을 받아요. 이후엔 바뀐 부분만 받고 재설치는 없어요. 창을 닫아도 트레이에서 계속 받아요.",
    ],
  ];
  let slide = 0;
  function showSlide(i) {
    slide = i % SLIDES.length;
    const [k, h, p] = SLIDES[slide];
    $("ik").textContent = k;
    $("ih").textContent = h;
    $("ip").textContent = p;
    $("dots").replaceChildren(
      ...SLIDES.map((_, j) => {
        const dot = document.createElement("i");
        if (j === slide) dot.className = "on";
        return dot;
      }),
    );
    const el = $("intro");
    el.classList.remove("fade");
    void el.offsetWidth; // 애니메이션을 다시 시작하게
    el.classList.add("fade");
  }

  function cell(cls) {
    const td = document.createElement("td");
    if (cls) td.className = cls;
    return td;
  }

  function row(r) {
    const tr = document.createElement("tr");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = r.selected;
    box.disabled = !r.editable;
    box.addEventListener("change", () => {
      state.select(r.name, box.checked);
      render();
    });
    const n = cell("n");
    n.append(box);

    const main = cell();
    const label = document.createElement("div");
    label.textContent = r.label;
    const bar = document.createElement("div");
    bar.className = "bar";
    const fill = document.createElement("i");
    fill.style.width = r.pct + "%";
    bar.append(fill);
    const st = document.createElement("div");
    st.className = "st";
    const text = document.createElement("span");
    text.textContent = r.status;
    if (r.tone) text.className = r.tone;
    st.append(text);
    main.append(label, bar, st);

    const size = cell("s");
    size.textContent = r.size;
    tr.append(n, main, size);
    return tr;
  }

  function render() {
    const v = state.view(Date.now());
    if (v.title) $("title").textContent = v.title;
    if (v.desc) $("desc").textContent = v.desc;
    $("tb").replaceChildren(...v.rows.map(row));
    $("hint").textContent = v.hint.text;
    $("hint").className = "hint" + (v.hint.tone ? " " + v.hint.tone : "");
    $("start").textContent = v.start.label;
    $("start").disabled = v.start.disabled;
    $("retry").hidden = !v.retry;
    $("total").hidden = !v.overall;
    if (v.overall) {
      $("tpct").textContent = v.overall.pct + "%";
      $("tbar").style.width = v.overall.pct + "%";
      $("teta").textContent = v.overall.text;
    }
  }

  S.onEvent((ev) => {
    state.apply(ev, Date.now());
    render();
  });
  function start() {
    state.begin();
    render();
    S.start({ optional: state.view(Date.now()).optional });
  }
  $("start").addEventListener("click", start);
  $("retry").addEventListener("click", start);
  $("logs").addEventListener("click", () => S.openLogs());

  showSlide(0);
  setInterval(() => showSlide(slide + 1), 6000);
  setInterval(() => state.running && render(), 1000); // 남은 시간 · 기다림 표시를 이벤트가 없어도 갱신
  render();
  S.ready();
})();
