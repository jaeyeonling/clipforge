// clipforge engine UI v0 — vanilla JS, 빌드 없음. API: /api/*, 이벤트: /ws
const $ = (s) => document.querySelector(s);
const state = { episode: localStorage.getItem("cf.episode") || null, job: null, running: false, candidates: [] };
const REASONS = ["", "재미없음", "임팩트없음", "중복", "잘림", "맥락없음", "기타"];
const STAGE_INPUTS = [["#stPrep", "prep"], ["#stTr", "transcribe"], ["#stSig", "signals"], ["#stShorts", "shorts"],
  ["#stExport", "export"], ["#stXml", "xml"], ["#stWeak", "weaklabel"], ["#stEval", "eval"]];

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = j.error || (Array.isArray(j.detail) ? { message: j.detail.map((d) => d.msg + " @" + d.loc.join(".")).join("; ") } : { message: j.detail || r.statusText });
    throw new Error(`${e.code ? e.code + " " : ""}${e.message || ""}${e.hint ? " — " + e.hint : ""}`);
  }
  return j;
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (t) => { t = Math.max(0, Math.floor(t)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };
const toast = (msg, bad = false) => { const t = $("#toast"); t.textContent = msg; t.className = "toast show" + (bad ? " bad" : ""); clearTimeout(t._h); t._h = setTimeout(() => (t.className = "toast"), 3200); };

async function loadHealth() {
  const h = await api("/api/health");
  const ok = (b) => `<span class="${b ? "ok" : "bad"}">${b ? "OK" : "없음"}</span>`;
  $("#health").innerHTML = `ffmpeg ${ok(h.ffmpeg_ok)} · NVENC ${ok(h.nvenc)} · GPU <b>${esc(h.gpu || "-")}</b> · Whisper GPU ${ok(h.whisper_gpu)} · OCR ${ok(h.rapidocr)} · 폰트 ${ok(h.fonts_ok)}`;
  $("#health").title = `app: ${h.app_root}\ndata: ${h.data_root}\nffmpeg: ${h.ffmpeg || "-"}`;
}

async function loadEpisodes() {
  const eps = await api("/api/episodes");
  const ul = $("#episodes"); ul.innerHTML = "";
  for (const e of eps) {
    const li = document.createElement("li");
    li.className = e.id === state.episode ? "active" : "";
    const st = Object.entries(e.stages).map(([k, v]) => `<span class="${v ? "done" : ""}">${k}</span>`).join("");
    li.innerHTML = `<div class="id">${esc(e.id)}</div><div class="meta">${esc(e.title || "")}</div>
      <div class="meta">${e.duration ? fmt(e.duration) + " · " + e.width + "×" + e.height + " · " + esc(e.game || "") : "미처리"}</div><div class="stages">${st}</div>`;
    li.onclick = () => selectEpisode(e.id);
    ul.appendChild(li);
  }
  if (!state.episode && eps.length) selectEpisode(eps[0].id);
}

async function selectEpisode(id) {
  state.episode = id; localStorage.setItem("cf.episode", id);
  $("#epTitle").textContent = id;
  await loadEpisodes(); await loadCandidates();
}

async function loadCandidates() {
  if (!state.episode) return;
  const c = await api(`/api/episodes/${state.episode}/candidates`);
  state.candidates = c;
  const box = $("#cands"); box.innerHTML = "";
  if (!c.length) { box.innerHTML = `<div class="meta">후보 없음 — 실행을 눌러 파이프라인을 돌리세요.</div>`; return; }
  for (const r of c) {
    const el = document.createElement("div"); el.className = "cand" + (r.decision ? " dec-" + r.decision : "");
    const ev = r.evidence || {};
    el.innerHTML = `
      ${r.media_url ? `<video src="${r.media_url}" controls preload="metadata" playsinline></video>` : `<div class="novideo">초안 없음 (export 단계 미실행)</div>`}
      <div class="body">
        <div class="title">#${r.rank ?? ""} ${esc(r.variant)} · ${fmt(r.start)}–${fmt(r.end)} <span class="meta">(${Math.round(r.end - r.start)}s)</span></div>
        <div class="hook">${esc((r.hook_lines || []).join(" / "))}</div>
        <div class="meta">점수 ${Number(r.score).toFixed(2)} · 앵커 ${fmt(r.anchor)} ${esc((ev.anchor_kinds || []).join("+"))} · 컷 ${ev.n_cuts ?? "-"} · 자막 ${r.subtitle_cues ?? "-"}</div>
        <div class="dec">
          <button class="keep ${r.decision === "keep" ? "on-keep" : ""}" title="쓸 만함 (정답으로 저장)">keep</button>
          <button class="no ${r.decision === "no" ? "on-no" : ""}" title="안 씀 (사유 선택)">no</button>
          <select class="reason" title="no 사유">${REASONS.map((x) => `<option ${x === r.reason ? "selected" : ""}>${x || "사유"}</option>`).join("")}</select>
        </div>
      </div>`;
    const send = async (label) => {
      const sel = el.querySelector(".reason");
      const reason = sel.value === "사유" ? "" : sel.value;
      const cur = r.decision === label ? "" : label;          // 같은 버튼 다시 누르면 해제
      if (cur === "no" && !reason) { toast("no 는 사유를 골라 주세요", true); sel.focus(); return; }
      await api(`/api/episodes/${state.episode}/decision`, { method: "POST", body: JSON.stringify({ start: r.start, end: r.end, label: cur, reason, file: r.file || "" }) });
      toast(cur ? `${cur} 저장됨` : "판정 해제");
      await loadCandidates(); await loadMetrics();
    };
    el.querySelector(".keep").onclick = () => send("keep").catch((e) => toast(e.message, true));
    el.querySelector(".no").onclick = () => send("no").catch((e) => toast(e.message, true));
    box.appendChild(el);
  }
}

async function loadMetrics() {
  const m = await api("/api/metrics");
  const tb = $("#metrics tbody"); tb.innerHTML = "";
  for (const r of m) tb.innerHTML += `<tr><td>${esc(r.episode)}</td><td>${r.labels}</td><td>${r.keep}</td><td>${r.no}</td><td>${r.hit1 ?? "-"}</td><td>${r.hit3 ?? "-"}</td><td>${r.mrr ?? "-"}</td></tr>`;
  if (!m.length) tb.innerHTML = `<tr><td colspan="7" class="meta">라벨이 있는 회차가 없습니다</td></tr>`;
}

async function loadJobs() {
  const js = await api("/api/jobs");
  const ul = $("#jobs"); ul.innerHTML = "";
  for (const j of js.slice().reverse()) {
    const dur = j.finished && j.started ? ` · ${Math.round(j.finished - j.started)}s` : "";
    ul.innerHTML += `<li><b>${esc(j.episode)}</b> <span class="st-${j.status}">${j.status}</span> ${esc(j.stage)} ${j.pct}%${dur}<br><span class="meta">${esc(j.message || j.error || "")}</span></li>`;
  }
  if (!js.length) ul.innerHTML = `<li class="meta">아직 실행한 작업이 없습니다</li>`;
}

function setRunning(on) { state.running = on; $("#runBtn").disabled = on; $("#cancelBtn").disabled = !on; }
function setProgress(pct, text) { $("#bar").style.width = `${pct}%`; $("#ptext").textContent = `${Math.round(pct)}% ${text || ""}`; }
function appendLog(line) { const l = $("#log"); l.textContent += line + "\n"; l.scrollTop = l.scrollHeight; }

async function run() {
  if (!state.episode) return toast("회차를 먼저 선택하세요", true);
  const stages = STAGE_INPUTS.filter(([s]) => $(s).checked).map(([, n]) => n);
  if (!stages.length) return toast("단계를 하나 이상 선택하세요", true);
  const params = { layout: $("#layout").value, k: Number($("#topk").value) || 5, force: $("#force").checked };
  const j = await api("/api/jobs", { method: "POST", body: JSON.stringify({ episode: state.episode, stages, params }) });
  state.job = j.id; setRunning(true); $("#log").textContent = ""; setProgress(0, "대기열");
  toast(`작업 시작: ${stages.join(" → ")}`);
  await loadJobs();
}

function connectWs() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (state.job && ev.job_id !== state.job) { loadJobs(); return; }
    if (ev.type === "progress") setProgress(ev.pct, `${ev.stage} ${ev.message || ""}`);
    if (ev.type === "log") appendLog(ev.message);
    if (ev.type === "done" || ev.type === "error") {
      setRunning(false);
      if (ev.type === "error") { setProgress(parseFloat($("#bar").style.width) || 0, `오류: ${ev.message}`); appendLog(`오류 ${ev.code}: ${ev.message}\n${ev.hint || ""}`); toast(`오류: ${ev.message}`, true); }
      else { setProgress(100, ev.status === "cancelled" ? "취소됨" : "완료"); toast(ev.status === "cancelled" ? "취소됨" : "완료"); }
      loadEpisodes(); loadCandidates(); loadMetrics();
    }
    loadJobs();
  };
  ws.onclose = () => setTimeout(connectWs, 1500);
}

// ---- 캘리브레이션 ----
const calib = { game: null, rois: null, bands: null };
async function calibCheck() {
  if (!state.episode) return toast("회차를 먼저 선택하세요", true);
  const r = await api(`/api/episodes/${state.episode}/calibrate`);
  const ul = $("#calibChecks"); ul.innerHTML = "";
  if (!r.ok) { $("#calibStatus").textContent = r.error; return; }
  calib.game = r.game;
  $("#calibStatus").innerHTML = `${esc(r.game)} · ${r.resolution.join("×")} · 전체 <span class="badge ${r.status}">${r.status}</span>`;
  for (const c of r.checks) ul.innerHTML += `<li><span class="badge ${c.status}">${c.status}</span><div><b>${esc(c.name)}</b> ${c.rate == null ? "" : Math.round(c.rate * 100) + "%"} <span class="meta">${esc(c.detail)}</span>${c.hint ? `<div class="hint">${esc(c.hint)}</div>` : ""}</div></li>`;
  await calibPreview();
}
async function calibPreview(rois) {
  if (!state.episode) return;
  const t = Number($("#calibT").value) || 0;
  const r = await api(`/api/episodes/${state.episode}/calibrate/preview`, { method: "POST", body: JSON.stringify({ t, rois: rois || null }) });
  const img = $("#calibImg"); img.src = r.url; img.hidden = false;
}
async function roiEdit() {
  if (!calib.game) { const e = await api(`/api/episodes/${state.episode}`); calib.game = e.game || "d2r"; }
  const prof = await api(`/api/profiles/${calib.game}`);
  calib.rois = prof.rois; calib.bands = prof.panel_bands;
  const ed = $("#roiEditor"); ed.hidden = false;
  ed.innerHTML = `<div class="roi"><span class="name">ROI (비율)</span><span>x</span><span>y</span><span>w</span><span>h</span></div>` +
    Object.entries(prof.rois).map(([k, v]) => `<div class="roi" data-k="${esc(k)}"><span class="name">${esc(k)}</span>${v.map((x) => `<input type="number" step="0.005" min="0" max="1" value="${x}">`).join("")}</div>`).join("") +
    `<div class="btns"><button id="roiPreview" class="ghost small">미리보기 갱신</button><button id="roiSave" class="primary small">프로필 저장</button><button id="roiClose" class="ghost small">닫기</button></div>
     <div class="meta">네이티브 크롭(배너·채팅)이 바뀌는 ROI 는 다음 prep(강제 재계산)부터 반영됩니다.</div>`;
  const read = () => Object.fromEntries([...ed.querySelectorAll(".roi[data-k]")].map((row) => [row.dataset.k, [...row.querySelectorAll("input")].map((i) => Number(i.value))]));
  $("#roiPreview").onclick = () => calibPreview(read()).catch((e) => toast(e.message, true));
  $("#roiSave").onclick = () => api(`/api/profiles/${calib.game}`, { method: "PUT", body: JSON.stringify({ rois: read() }) }).then((r) => toast(r.note || "저장됨")).catch((e) => toast(e.message, true));
  $("#roiClose").onclick = () => (ed.hidden = true);
}
$("#calibBtn").onclick = () => calibCheck().catch((e) => toast(e.message, true));
$("#calibPrevBtn").onclick = () => calibPreview().catch((e) => toast(e.message, true));
$("#roiEditBtn").onclick = () => roiEdit().catch((e) => toast(e.message, true));

$("#runBtn").onclick = () => run().catch((e) => toast(e.message, true));
$("#cancelBtn").onclick = () => state.job && api(`/api/jobs/${state.job}/cancel`, { method: "POST" }).then(loadJobs).catch((e) => toast(e.message, true));
$("#addBtn").onclick = () => api("/api/episodes", { method: "POST", body: JSON.stringify({ video_path: $("#addPath").value.trim(), title: $("#addTitle").value.trim() }) })
  .then((e) => { $("#addPath").value = ""; $("#addTitle").value = ""; toast(`등록: ${e.id}`); selectEpisode(e.id); }).catch((e) => toast(e.message, true));
$("#presetFull").onclick = () => STAGE_INPUTS.forEach(([s, n]) => ($(s).checked = !["weaklabel", "eval"].includes(n)));
$("#presetRank").onclick = () => STAGE_INPUTS.forEach(([s, n]) => ($(s).checked = ["shorts", "export", "xml", "eval"].includes(n)));

loadHealth(); loadEpisodes().then(() => state.episode && selectEpisode(state.episode)); loadMetrics(); loadJobs(); connectWs();
