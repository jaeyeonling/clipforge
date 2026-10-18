import { useEffect, useRef, useState } from "react";
import { DEFAULT_STAGES, KIND_LABEL, STAGES, STAGE_LABEL, type EpisodeKind, type Layout, type StageName } from "../api/types";
import { Badge, Button, Card, Progress, Spinner, cx, fmtDur } from "../components/ui";
import { inShell, shell } from "../shell";
import { useApp } from "../state/store";

const PRESETS: { key: string; label: string; title: string; kinds: EpisodeKind[]; stages: StageName[] }[] = [
  { key: "full", label: "전체", title: "처음 처리하는 회차: 준비 → 결과까지", kinds: ["edited", "original"], stages: [] },
  { key: "rank", label: "순위만", title: "캐시 재사용: 쇼츠 후보·초안·XML·평가만 (규칙을 바꾼 뒤)", kinds: ["edited"], stages: ["shorts", "export", "xml", "eval"] },
  { key: "points", label: "포인트만", title: "캐시 재사용: 편집 포인트 후보·평가만 (가중치를 바꾼 뒤)", kinds: ["original"], stages: ["candidates", "eval"] },
  { key: "eval", label: "평가만", title: "정답이 바뀐 뒤 지표만", kinds: ["edited", "original"], stages: ["eval"] },
];
const STATUS_KO: Record<string, string> = { queued: "대기", running: "실행 중", done: "완료", error: "오류", cancelled: "취소" };
/** 회차 종류별로 보여줄 단계 (다른 종류의 단계는 숨긴다) */
const STAGES_FOR: Record<EpisodeKind, StageName[]> = {
  edited: ["prep", "transcribe", "signals", "shorts", "export", "xml", "align", "weaklabel", "eval"],
  original: ["prep", "transcribe", "signals", "candidates", "align", "xml", "eval"],
};

export function Pipeline() {
  const { selected, activeJob, runJob, cancelJob, fail, runError, dismissError, toast } = useApp();
  const kind: EpisodeKind = selected?.kind || "edited";
  const [stages, setStages] = useState<Set<StageName>>(new Set(DEFAULT_STAGES.edited));
  const [layout, setLayout] = useState<Layout>("card");
  const [k, setK] = useState(5);
  const [force, setForce] = useState(false);
  const [finalPath, setFinalPath] = useState("");
  const [shortsPaths, setShortsPaths] = useState<string[]>([]);
  const [threshold, setThreshold] = useState(1.5);
  const lastKind = useRef<EpisodeKind | null>(null);
  useEffect(() => { if (lastKind.current !== kind) { lastKind.current = kind; setStages(new Set(DEFAULT_STAGES[kind])); } }, [kind]);

  const running = !!activeJob && (activeJob.status === "running" || activeJob.status === "queued");
  const visible = STAGES_FOR[kind];
  const toggle = (s: StageName) => setStages((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });
  const ordered = STAGES.filter((s) => stages.has(s) && visible.includes(s));
  const needsFinal = ordered.includes("align") && kind === "original";
  const needsShorts = ordered.includes("align") && kind === "edited";

  const pickFinal = async () => { if (!shell) return; try { const ps = await shell.shell.pickVideos(); if (ps[0]) setFinalPath(ps[0]); } catch (e) { fail(e); } };
  const pickShorts = async () => { if (!shell) return; try { const ps = await shell.shell.pickVideos(); if (ps.length) setShortsPaths((cur) => [...new Set([...cur, ...ps])]); } catch (e) { fail(e); } };
  const start = async () => {
    if (!selected) return;
    if (!ordered.length) return fail(new Error("단계를 하나 이상 선택하세요"));
    if (needsFinal && !finalPath.trim()) { toast("align 에는 최종본(편집본) 파일이 필요합니다", true); return; }
    if (needsShorts && !shortsPaths.length) { toast("쇼츠 역매핑에는 친구 쇼츠 파일이 필요합니다", true); return; }
    try { await runJob(selected.id, ordered, { layout, k, force, kind, threshold, final: needsFinal ? finalPath.trim() : undefined, shorts: needsShorts ? shortsPaths : undefined }); } catch (e) { fail(e); }
  };
  const retry = async () => {
    const j = runError?.job; if (!j) return;
    const p = j.params as Record<string, unknown>;
    try { await runJob(j.episode, j.stages, { layout: (p.layout as Layout) || "card", k: Number(p.k) || 5, force: !!p.force, kind: p.kind as EpisodeKind, final: p.final as string | undefined, shorts: p.shorts as string[] | undefined, threshold: Number(p.threshold) || undefined }); } catch (e) { fail(e); }
  };

  const state = activeJob?.status === "error" ? "error" : activeJob?.status === "done" ? "done" : "";
  const elapsed = activeJob?.started ? ((activeJob.finished || Date.now() / 1000) - activeJob.started) : 0;

  return (
    <>
      <Card title={`파이프라인 · ${KIND_LABEL[kind]}`} right={selected && <span className="muted xs">{selected.id}</span>}>
        <div className="stage-grid">
          {visible.map((s) => (
            <label key={s} className={cx("stage-opt", stages.has(s) && "on")}>
              <input type="checkbox" checked={stages.has(s)} onChange={() => toggle(s)} disabled={running} />
              <span><span className="name">{s}</span><br /><span className="ko">{STAGE_LABEL[s]}</span></span>
              {selected?.stages?.[s] && <span className="done"><Badge tone="ok">완료</Badge></span>}
            </label>
          ))}
        </div>
        {needsShorts && (
          <div className="shorts-pick">
            <div className="row">
              <span className="small">친구 쇼츠 파일 — 이 회차에서 잘라 올린 쇼츠를 주면 어느 구간인지 찾아 정답(keep)으로 기록합니다</span>
              <span className="grow" style={{ flex: 1 }} />
              {inShell ? <Button size="sm" onClick={pickShorts} disabled={running}>쇼츠 추가…</Button>
                : <input className="field sm" style={{ minWidth: 260 }} placeholder="경로 입력 후 Enter (폴더도 됨)" disabled={running} onKeyDown={(e) => { if (e.key === "Enter") { const v = (e.target as HTMLInputElement).value.trim(); if (v) { setShortsPaths((cur) => [...new Set([...cur, v])]); (e.target as HTMLInputElement).value = ""; } } }} />}
            </div>
            {shortsPaths.length > 0 && <ul className="shorts-list">{shortsPaths.map((sp) => <li key={sp}><span className="mono xs">{sp}</span><Button size="sm" variant="ghost" onClick={() => setShortsPaths((cur) => cur.filter((x) => x !== sp))} disabled={running}>✕</Button></li>)}</ul>}
          </div>
        )}
        {needsFinal && (
          <div className="row" style={{ marginTop: 12 }}>
            <span className="small">최종본(편집본) 파일</span>
            <input className="field" style={{ flex: 1, minWidth: 240 }} placeholder="친구 편집본 mp4 경로 — 원본의 어느 구간이 살아남았는지 정답을 만듭니다" value={finalPath} onChange={(e) => setFinalPath(e.target.value)} disabled={running} />
            {inShell && <Button size="sm" onClick={pickFinal} disabled={running}>찾기…</Button>}
          </div>
        )}
        <div className="row" style={{ marginTop: 12 }}>
          {PRESETS.filter((p) => p.kinds.includes(kind)).map((p) => (
            <Button key={p.key} variant="ghost" size="sm" title={p.title} onClick={() => setStages(new Set(p.stages.length ? p.stages : DEFAULT_STAGES[kind]))} disabled={running}>{p.label}</Button>
          ))}
          <span className="sep" />
          {kind === "edited" ? (
            <>
              <label className="check">레이아웃
                <select className="field sm" value={layout} onChange={(e) => setLayout(e.target.value as Layout)} disabled={running} title="card = 친구 확정 포맷(제목 띠 + 템 창 크롭 + 채팅). feed 는 실험용">
                  <option value="card">card (확정)</option><option value="feed">feed (실험)</option>
                </select>
              </label>
              <label className="check">상위 <input className="field sm num" type="number" min={1} max={10} value={k} onChange={(e) => setK(Number(e.target.value) || 5)} disabled={running} /></label>
            </>
          ) : (
            <label className="check" title="후보 임계값 — 낮출수록 후보가 늘어 recall ↑ coverage ↑">임계값 <input className="field sm num" type="number" step={0.1} min={0.2} max={5} value={threshold} onChange={(e) => setThreshold(Number(e.target.value) || 1.5)} disabled={running} /></label>
          )}
          <label className={cx("check", force && "on")} title="캐시를 무시하고 다시 계산"><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} disabled={running} /> 강제 재계산</label>
          <span className="grow" style={{ flex: 1 }} />
          {running ? <Button variant="danger" onClick={() => cancelJob().catch(fail)}>취소</Button>
            : <Button variant="primary" onClick={start} disabled={!selected || !ordered.length}>실행 {ordered.length ? `(${ordered.length}단계)` : ""}</Button>}
        </div>
        {kind === "original" && <p className="muted xs" style={{ marginTop: 8 }}>원본은 길어서 OCR 이 무거운 신호(채팅 텍스트)와 편집본 전용 신호(컷 밀도·줌 강조)는 돌리지 않습니다. 득템 배너는 화면이 바뀔 때만 읽습니다.</p>}
        <div className="runbar" style={{ marginTop: 14 }}>
          <div>
            <Progress pct={activeJob?.pct ?? 0} state={state} indeterminate={activeJob?.status === "queued"} />
            <div className="status" style={{ marginTop: 6 }}>
              {running && <Spinner />}
              {activeJob ? (
                <><b>{STATUS_KO[activeJob.status] || activeJob.status}</b>
                  <span>{activeJob.stage && activeJob.status === "running" ? `${activeJob.stage} ${Math.round(activeJob.pct)}% · ` : ""}{activeJob.message}</span>
                  {elapsed > 0 && <span className="muted">· {fmtDur(elapsed)}</span>}</>
              ) : <span className="muted">대기 중 — 회차를 고르고 실행을 누르세요.</span>}
            </div>
          </div>
        </div>
      </Card>

      {runError && (
        <div className="errbox" role="alert">
          <div className="head"><span className="code">{runError.info.code}</span><span className="msg">{runError.info.message}</span></div>
          <div className="hint">{runError.info.hint || (runError.info.kind === "internal" ? "내부 오류입니다. 로그를 확인하세요." : "")}</div>
          <div className="btns">
            {runError.job && <Button variant="primary" size="sm" onClick={retry}>같은 설정으로 다시 실행</Button>}
            <Button variant="ghost" size="sm" onClick={dismissError}>닫기</Button>
          </div>
        </div>
      )}

      <LogPane />
    </>
  );
}

export function LogPane() {
  const { log, logTitle, logPath, clearLog } = useApp();
  const [errOnly, setErrOnly] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { const el = box.current; if (el) el.scrollTop = el.scrollHeight; }, [log]);
  return (
    <div className="logpane" style={{ marginTop: 12 }}>
      <div className="logbar">
        <span className="grow" title={logPath}>{logTitle}{logPath ? ` — ${logPath}` : ""}</span>
        <label className="check xs"><input type="checkbox" checked={errOnly} onChange={(e) => setErrOnly(e.target.checked)} /> 오류만</label>
        <Button variant="ghost" size="sm" onClick={clearLog}>지우기</Button>
      </div>
      <div ref={box} className={cx("log", errOnly && "err-only")}>
        {log.length ? log.map((l, i) => <div key={i} className={cx("line", l.level)}>{l.stage && <span className="st">{l.stage}</span>}{l.message}</div>)
          : <div className="nothing">작업을 실행하면 진행 로그가 여기 쌓입니다. 지표·작업 탭에서 이전 작업을 눌러도 볼 수 있습니다.</div>}
      </div>
    </div>
  );
}
