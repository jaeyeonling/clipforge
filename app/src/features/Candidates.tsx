import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { REASONS, type Candidate } from "../api/types";
import { Button, Empty, Spinner, cx, fmtTime } from "../components/ui";
import { useApp } from "../state/store";

type Filter = "all" | "undecided" | "keep" | "no";
const keyOf = (c: Candidate) => `${c.start}-${c.end}`;
const isTyping = () => { const el = document.activeElement; return !!el && ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName); };

/**
 * 후보 리뷰. 키보드: ← → 이동 · K keep · N 다음 1~6 으로 사유 선택(no) · Space 재생/정지 · C 비교에 담기(2개) · Esc 닫기
 * 판정은 labels.csv 에 바로 저장된다. 같은 버튼을 다시 누르면 해제.
 */
export function Candidates() {
  const { selected, tick, toast, fail } = useApp();
  const [items, setItems] = useState<Candidate[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [focus, setFocus] = useState(0);
  const [reasonPrompt, setReasonPrompt] = useState(false);
  const [compare, setCompare] = useState<string[]>([]);          // keyOf 목록 (최대 2)
  const videos = useRef(new Map<string, HTMLVideoElement>());

  const load = useCallback(async () => {
    if (!selected) { setItems([]); return; }
    try { setItems(await api.candidates(selected.id)); } catch (e) { fail(e); setItems([]); }
  }, [selected, fail]);
  useEffect(() => { load(); }, [load, tick]);
  useEffect(() => { setCompare([]); setFocus(0); }, [selected?.id]);

  const shown = useMemo(() => (items || []).filter((c) => filter === "all" || (filter === "undecided" ? !c.decision : c.decision === filter)), [items, filter]);
  useEffect(() => { if (focus >= shown.length) setFocus(Math.max(0, shown.length - 1)); }, [shown.length, focus]);

  const decide = useCallback(async (c: Candidate, label: "keep" | "no", reason: string) => {
    if (!selected) return;
    const next = c.decision === label ? "" : label;              // 같은 버튼 다시 누르면 해제
    if (next === "no" && !reason) { toast("no 는 사유를 골라 주세요 (N 다음 1~6)", true); return; }
    setBusy(keyOf(c));
    try {
      await api.decide(selected.id, c, next, next === "no" ? reason : "");
      toast(next ? `${next} 저장됨${next === "no" ? " · " + reason : ""}` : "판정 해제");
      setItems((cur) => cur?.map((x) => (keyOf(x) === keyOf(c) ? { ...x, decision: next, reason: next === "no" ? reason : "" } : x)) ?? cur);
    } catch (e) { fail(e); } finally { setBusy(null); }
  }, [selected, toast, fail]);

  const toggleCompare = useCallback((c: Candidate) => {
    setCompare((cur) => (cur.includes(keyOf(c)) ? cur.filter((k) => k !== keyOf(c)) : [...cur.slice(-1), keyOf(c)]));
  }, []);

  // ---- 키보드 ----
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping() || !shown.length) return;
      const c = shown[focus];
      if (reasonPrompt) {
        if (/^[1-6]$/.test(e.key)) { e.preventDefault(); setReasonPrompt(false); decide(c, "no", REASONS[Number(e.key) - 1]); return; }
        if (e.key === "Escape") { setReasonPrompt(false); return; }
      }
      switch (e.key) {
        case "ArrowRight": case "ArrowDown": e.preventDefault(); setFocus((i) => Math.min(shown.length - 1, i + 1)); break;
        case "ArrowLeft": case "ArrowUp": e.preventDefault(); setFocus((i) => Math.max(0, i - 1)); break;
        case "Home": e.preventDefault(); setFocus(0); break;
        case "End": e.preventDefault(); setFocus(shown.length - 1); break;
        case "k": case "K": e.preventDefault(); decide(c, "keep", ""); break;
        case "n": case "N": e.preventDefault(); if (c.decision === "no") decide(c, "no", c.reason || ""); else setReasonPrompt(true); break;
        case " ": { e.preventDefault(); const v = videos.current.get(keyOf(c)); if (v) { v.paused ? v.play() : v.pause(); } break; }
        case "c": case "C": e.preventDefault(); toggleCompare(c); break;
        case "Escape": setCompare([]); break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [shown, focus, reasonPrompt, decide, toggleCompare]);

  useEffect(() => {   // 포커스 카드가 보이게
    const c = shown[focus]; if (!c) return;
    document.querySelector<HTMLElement>(`[data-key="${keyOf(c)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [focus, shown]);

  if (!selected) return <Empty title="회차를 선택하세요" />;
  if (items === null) return <div className="row"><Spinner /> <span className="muted">후보 읽는 중…</span></div>;
  if (!items.length) return <Empty title="후보가 없습니다">파이프라인 탭에서 실행하면 순간 순위가 여기 뜹니다.</Empty>;

  const counts = { all: items.length, undecided: items.filter((c) => !c.decision).length, keep: items.filter((c) => c.decision === "keep").length, no: items.filter((c) => c.decision === "no").length };
  const cmpItems = compare.map((k) => items.find((c) => keyOf(c) === k)).filter((c): c is Candidate => !!c);

  return (
    <>
      <div className="filters">
        {(["all", "undecided", "keep", "no"] as Filter[]).map((f) => (
          <Button key={f} variant="ghost" size="sm" className={cx(filter === f && "active")} onClick={() => { setFilter(f); setFocus(0); }}>
            {{ all: "전체", undecided: "미판정", keep: "keep", no: "no" }[f]} {counts[f]}
          </Button>
        ))}
        <span className="keys" title="키보드 단축키">
          <kbd>←</kbd><kbd>→</kbd> 이동 · <kbd>K</kbd> keep · <kbd>N</kbd>+<kbd>1~6</kbd> no 사유 · <kbd>Space</kbd> 재생 · <kbd>C</kbd> 비교 · <kbd>Esc</kbd> 닫기
        </span>
      </div>
      {reasonPrompt && (
        <div className="reason-prompt">
          <b>no 사유</b> {REASONS.map((r, i) => <button key={r} className="btn sm" onClick={() => { setReasonPrompt(false); decide(shown[focus], "no", r); }}><kbd>{i + 1}</kbd> {r}</button>)}
          <Button size="sm" variant="ghost" onClick={() => setReasonPrompt(false)}>취소 (Esc)</Button>
        </div>
      )}
      {cmpItems.length > 0 && <ComparePanel items={cmpItems} onDecide={decide} onClose={() => setCompare([])} onRemove={toggleCompare} />}
      <div className="cands">
        {shown.map((c, i) => (
          <CandidateCard key={keyOf(c)} c={c} focused={i === focus} inCompare={compare.includes(keyOf(c))} busy={busy === keyOf(c)}
            onFocus={() => setFocus(i)} onDecide={decide} onCompare={() => toggleCompare(c)}
            videoRef={(el) => { if (el) videos.current.set(keyOf(c), el); else videos.current.delete(keyOf(c)); }} />
        ))}
        {!shown.length && <Empty title="이 필터에 해당하는 후보가 없습니다" />}
      </div>
    </>
  );
}

function CandidateCard({ c, focused, inCompare, busy, onFocus, onDecide, onCompare, videoRef }: {
  c: Candidate; focused: boolean; inCompare: boolean; busy: boolean; onFocus: () => void;
  onDecide: (c: Candidate, label: "keep" | "no", reason: string) => void; onCompare: () => void; videoRef: (el: HTMLVideoElement | null) => void;
}) {
  const [reason, setReason] = useState(c.reason || "");
  useEffect(() => setReason(c.reason || ""), [c.reason]);
  const ev = c.evidence || {};
  const len = Math.round(c.end - c.start);
  return (
    <article className={cx("cand", c.decision, focused && "focused", inCompare && "in-compare")} data-key={keyOf(c)} onClick={onFocus} tabIndex={-1}>
      {c.media_url ? <video ref={videoRef} src={c.media_url} controls preload="metadata" playsInline /> : <div className="novideo">초안 없음 (export 단계 미실행)</div>}
      <div className="body">
        <div className="rank"><span className="n">#{c.rank ?? "-"}</span><span>{c.variant}</span><span className="muted small">{fmtTime(c.start)}–{fmtTime(c.end)} · {len}s</span>
          <button className={cx("cmp", inCompare && "on")} title="비교에 담기 (C)" onClick={(e) => { e.stopPropagation(); onCompare(); }}>⇄</button></div>
        {c.hook_lines?.length ? <div className="hook">{c.hook_lines.join(" / ")}</div> : null}
        <div className="meta">점수 {Number(c.score).toFixed(2)} · 앵커 {fmtTime(c.anchor)} {(ev.anchor_kinds || []).join("+")} · 컷 {ev.n_cuts ?? "-"} · 자막 {c.subtitle_cues ?? "-"}</div>
        <div className="dec">
          <Button size="sm" className={cx(c.decision === "keep" && "on-keep")} disabled={busy} onClick={(e) => { e.stopPropagation(); onDecide(c, "keep", reason); }} title="쓸 만함 (K)">keep</Button>
          <Button size="sm" className={cx(c.decision === "no" && "on-no")} disabled={busy} onClick={(e) => { e.stopPropagation(); onDecide(c, "no", reason); }} title="안 씀 (N → 사유)">no</Button>
          <select className="field sm" value={reason} onChange={(e) => setReason(e.target.value)} onClick={(e) => e.stopPropagation()} title="no 사유">
            <option value="">사유</option>{REASONS.map((r, i) => <option key={r} value={r}>{i + 1} {r}</option>)}
          </select>
        </div>
      </div>
    </article>
  );
}

function ComparePanel({ items, onDecide, onClose, onRemove }: { items: Candidate[]; onDecide: (c: Candidate, label: "keep" | "no", reason: string) => void; onClose: () => void; onRemove: (c: Candidate) => void }) {
  const refs = useRef<(HTMLVideoElement | null)[]>([]);
  const playAll = () => refs.current.forEach((v) => { if (v) { v.currentTime = 0; v.play().catch(() => {}); } });
  const pauseAll = () => refs.current.forEach((v) => v?.pause());
  return (
    <section className="compare">
      <div className="compare-head">
        <b>비교</b><span className="muted small">{items.length < 2 ? "하나 더 담으면 나란히 봅니다 (카드의 ⇄ 또는 C)" : "같은 순간의 다른 창이거나 중복인지 확인하세요"}</span>
        <span style={{ flex: 1 }} />
        <Button size="sm" onClick={playAll}>둘 다 처음부터</Button><Button size="sm" variant="ghost" onClick={pauseAll}>정지</Button><Button size="sm" variant="ghost" onClick={onClose}>닫기 (Esc)</Button>
      </div>
      <div className={cx("compare-grid", items.length === 1 && "one")}>
        {items.map((c, i) => (
          <div key={keyOf(c)} className={cx("compare-item", c.decision)}>
            {c.media_url ? <video ref={(el) => { refs.current[i] = el; }} src={c.media_url} controls preload="metadata" playsInline /> : <div className="novideo">초안 없음</div>}
            <div className="row between" style={{ marginTop: 6 }}>
              <span className="small"><b>#{c.rank}</b> {c.variant} · {fmtTime(c.start)}–{fmtTime(c.end)} · {Math.round(c.end - c.start)}s · 점수 {Number(c.score).toFixed(2)}</span>
              <span className="row">
                <Button size="sm" className={cx(c.decision === "keep" && "on-keep")} onClick={() => onDecide(c, "keep", "")}>keep</Button>
                <Button size="sm" className={cx(c.decision === "no" && "on-no")} onClick={() => onDecide(c, "no", c.reason || "중복")} title="사유: 중복">no (중복)</Button>
                <Button size="sm" variant="ghost" onClick={() => onRemove(c)}>빼기</Button>
              </span>
            </div>
            {c.hook_lines?.length ? <div className="muted xs">{c.hook_lines.join(" / ")}</div> : null}
          </div>
        ))}
      </div>
    </section>
  );
}
