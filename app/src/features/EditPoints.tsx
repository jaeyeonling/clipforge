import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { EditPointsResult } from "../api/types";
import { Badge, Button, Card, Empty, Spinner, cx, fmtTime } from "../components/ui";
import { useApp } from "../state/store";

/**
 * Phase 2: 원본 → 편집 포인트. 원본 영상 플레이어 + 후보 목록(정답 kept 와 겹침 표시) + 사람 판정(kept/no).
 * 키보드: ← → 이동 · Enter 재생(후보 시작으로) · K kept · N no · Esc 정지
 */
export function EditPoints() {
  const { selected, tick, toast, fail } = useApp();
  const [data, setData] = useState<EditPointsResult | null>(null);
  const [focus, setFocus] = useState(0);
  const [filter, setFilter] = useState<"all" | "missed" | "undecided">("all");
  const video = useRef<HTMLVideoElement>(null);

  const load = useCallback(async () => {
    if (!selected) { setData(null); return; }
    try { setData(await api.editpoints(selected.id)); } catch (e) { fail(e); setData(null); }
  }, [selected, fail]);
  useEffect(() => { load(); }, [load, tick]);
  useEffect(() => { setFocus(0); }, [selected?.id, filter]);

  const rows = (data?.candidates || []).filter((c) => filter === "all" || (filter === "undecided" ? !c.decision : !c.kept));
  const seek = useCallback((t: number, play = true) => { const v = video.current; if (!v) return; v.currentTime = Math.max(0, t); if (play) v.play().catch(() => {}); }, []);
  const decide = useCallback(async (idx: number, label: "kept" | "no") => {
    const c = data?.candidates[idx]; if (!c || !selected) return;
    const next = c.decision === label ? "" : label;
    try { await api.decideEditPoint(selected.id, c.start, c.end, next); toast(next ? `${next} 저장됨` : "판정 해제"); await load(); } catch (e) { fail(e); }
  }, [data, selected, toast, fail, load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement; if (el && ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName)) return;
      if (!rows.length) return;
      const c = rows[focus];
      switch (e.key) {
        case "ArrowDown": case "ArrowRight": e.preventDefault(); setFocus((i) => Math.min(rows.length - 1, i + 1)); break;
        case "ArrowUp": case "ArrowLeft": e.preventDefault(); setFocus((i) => Math.max(0, i - 1)); break;
        case "Enter": e.preventDefault(); seek(c.start - 2); break;
        case "k": case "K": e.preventDefault(); decide(c.idx, "kept"); break;
        case "n": case "N": e.preventDefault(); decide(c.idx, "no"); break;
        case "Escape": video.current?.pause(); break;
      }
    };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, [rows, focus, seek, decide]);

  if (!selected) return <Empty title="회차를 선택하세요" />;
  if (!data) return <div className="row"><Spinner /> <span className="muted">편집 포인트 읽는 중…</span></div>;
  if (!data.candidates.length) return <Empty title="편집 포인트 후보가 없습니다">원본 회차에서 파이프라인(신호 → candidates)을 실행하면 여기 뜹니다. 편집본(최종본)이 있으면 align 으로 정답을 만들어 recall 을 봅니다.</Empty>;

  const rep = data.report; const al = data.align;
  const total = data.candidates.reduce((a, c) => a + (c.end - c.start), 0);
  return (
    <div className="ep-layout">
      <div>
        <Card title="원본 재생" right={<span className="muted xs">{fmtTime(data.duration)} · 후보 {data.candidates.length}개 · 검토량 {fmtTime(total)} ({data.duration ? Math.round(100 * total / data.duration) : 0}%)</span>}>
          {data.video_url ? <video ref={video} className="ep-video" src={data.video_url} controls preload="metadata" /> : <div className="novideo" style={{ aspectRatio: "16/9" }}>영상 파일을 찾을 수 없습니다</div>}
          <div className="row small" style={{ marginTop: 8 }}>
            <span className="keys"><kbd>↑</kbd><kbd>↓</kbd> 이동 · <kbd>Enter</kbd> 2초 전부터 재생 · <kbd>K</kbd> kept · <kbd>N</kbd> no · <kbd>Esc</kbd> 정지</span>
          </div>
        </Card>
        <Card title="정답 · 지표">
          {rep ? (
            <table className="data"><tbody>
              <tr><td>recall</td><td className="num">{(rep.recall * 100).toFixed(0)}%</td><td className="muted xs">정답 {rep.n_labels}개 중 후보가 잡은 비율 — 1순위</td></tr>
              <tr><td>coverage</td><td className="num">{(rep.coverage * 100).toFixed(1)}%</td><td className="muted xs">검토해야 할 영상 비율 (목표 ≤ 10%)</td></tr>
              <tr><td>precision</td><td className="num">{(rep.precision * 100).toFixed(0)}%</td><td className="muted xs">후보 중 정답과 겹친 비율</td></tr>
              <tr><td>놓침</td><td className="num">{rep.missed.length}</td><td className="muted xs">{rep.missed.slice(0, 6).map((m) => `${fmtTime(m.start)}–${fmtTime(m.end)}`).join(", ")}{rep.missed.length > 6 ? " …" : ""}</td></tr>
            </tbody></table>
          ) : <p className="muted small">정답(kept)이 아직 없습니다. 파이프라인에서 최종본 파일을 지정해 align 을 실행하거나, 목록에서 직접 kept 를 표시하세요.</p>}
          {al && <p className="muted xs" style={{ marginTop: 8 }}>align: 최종본 {al.final} 의 {Math.round((al.matched_frac || 0) * 100)}% 매칭, {al.n_segments}구간{al.unmatched?.length ? ` · 미매칭 ${al.unmatched.length}곳(인트로·카드)` : ""}</p>}
          {data.signals.length > 0 && <p className="muted xs" style={{ marginTop: 4 }}>신호: {data.signals.join(", ")}</p>}
        </Card>
      </div>
      <Card title="후보" right={
        <span className="row">
          {(["all", "missed", "undecided"] as const).map((f) => <Button key={f} size="sm" variant="ghost" className={cx(filter === f && "active")} onClick={() => setFilter(f)}>{{ all: "전체", missed: "정답 아님", undecided: "미판정" }[f]}</Button>)}
        </span>}>
        <ul className="ep-list">
          {rows.map((c, i) => (
            <li key={c.idx} className={cx("ep-row", i === focus && "focused", c.kept && "kept", c.decision)} onClick={() => { setFocus(i); seek(c.start - 2); }}>
              <span className="t mono">{fmtTime(c.start)}–{fmtTime(c.end)}</span>
              <span className="d muted xs">{Math.round(c.end - c.start)}s</span>
              <span className="s mono">{c.score.toFixed(2)}</span>
              <span className="tags">{c.kept && <Badge tone="ok" title={c.kept_labels.join(", ")}>정답</Badge>}{c.decision && <Badge tone={c.decision === "kept" ? "ok" : "bad"}>{c.decision}</Badge>}</span>
              <span className="btns">
                <Button size="sm" className={cx(c.decision === "kept" && "on-keep")} onClick={(e) => { e.stopPropagation(); decide(c.idx, "kept"); }}>kept</Button>
                <Button size="sm" className={cx(c.decision === "no" && "on-no")} onClick={(e) => { e.stopPropagation(); decide(c.idx, "no"); }}>no</Button>
              </span>
            </li>
          ))}
          {!rows.length && <li className="muted small" style={{ padding: 10 }}>이 필터에 해당하는 후보가 없습니다</li>}
        </ul>
      </Card>
    </div>
  );
}
