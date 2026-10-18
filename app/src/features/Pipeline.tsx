import { useEffect, useRef, useState } from "react";
import { STAGES, STAGE_LABEL, type Layout, type StageName } from "../api/types";
import { Badge, Button, Card, Progress, Spinner, cx, fmtDur } from "../components/ui";
import { useApp } from "../state/store";

const PRESETS: { key: string; label: string; title: string; stages: StageName[] }[] = [
  { key: "full", label: "전체", title: "prep → xml 전체 (처음 처리하는 회차)", stages: ["prep", "transcribe", "signals", "shorts", "export", "xml"] },
  { key: "rank", label: "순위만", title: "캐시 재사용: 후보·초안·XML·평가만 (규칙을 바꾼 뒤)", stages: ["shorts", "export", "xml", "eval"] },
  { key: "eval", label: "평가만", title: "라벨이 바뀐 뒤 지표만", stages: ["eval"] },
];
const STATUS_KO: Record<string, string> = { queued: "대기", running: "실행 중", done: "완료", error: "오류", cancelled: "취소" };

export function Pipeline() {
  const { selected, activeJob, runJob, cancelJob, fail, runError, dismissError } = useApp();
  const [stages, setStages] = useState<Set<StageName>>(new Set(PRESETS[0].stages));
  const [layout, setLayout] = useState<Layout>("card");
  const [k, setK] = useState(5);
  const [force, setForce] = useState(false);

  const running = !!activeJob && (activeJob.status === "running" || activeJob.status === "queued");
  const toggle = (s: StageName) => setStages((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });
  const ordered = STAGES.filter((s) => stages.has(s));

  const start = async () => {
    if (!selected) return;
    if (!ordered.length) return fail(new Error("단계를 하나 이상 선택하세요"));
    try { await runJob(selected.id, ordered, { layout, k, force }); } catch (e) { fail(e); }
  };
  const retry = async () => {
    const j = runError?.job; if (!j) return;
    try { await runJob(j.episode, j.stages, { layout: (j.params.layout as Layout) || "card", k: Number(j.params.k) || 5, force: !!j.params.force }); } catch (e) { fail(e); }
  };

  const state = activeJob?.status === "error" ? "error" : activeJob?.status === "done" ? "done" : "";
  const elapsed = activeJob?.started ? ((activeJob.finished || Date.now() / 1000) - activeJob.started) : 0;

  return (
    <>
      <Card title="파이프라인" right={selected && <span className="muted xs">{selected.id}</span>}>
        <div className="stage-grid">
          {STAGES.map((s) => (
            <label key={s} className={cx("stage-opt", stages.has(s) && "on")}>
              <input type="checkbox" checked={stages.has(s)} onChange={() => toggle(s)} disabled={running} />
              <span><span className="name">{s}</span><br /><span className="ko">{STAGE_LABEL[s]}</span></span>
              {selected?.stages?.[s] && <span className="done"><Badge tone="ok">완료</Badge></span>}
            </label>
          ))}
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          {PRESETS.map((p) => <Button key={p.key} variant="ghost" size="sm" title={p.title} onClick={() => setStages(new Set(p.stages))} disabled={running}>{p.label}</Button>)}
          <span className="sep" />
          <label className="check">레이아웃
            <select className="field sm" value={layout} onChange={(e) => setLayout(e.target.value as Layout)} disabled={running} title="card = 친구 확정 포맷(제목 띠 + 템 창 크롭 + 채팅). feed 는 실험용">
              <option value="card">card (확정)</option><option value="feed">feed (실험)</option>
            </select>
          </label>
          <label className="check">상위 <input className="field sm num" type="number" min={1} max={10} value={k} onChange={(e) => setK(Number(e.target.value) || 5)} disabled={running} /></label>
          <label className={cx("check", force && "on")} title="캐시를 무시하고 다시 계산"><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} disabled={running} /> 강제 재계산</label>
          <span className="grow" style={{ flex: 1 }} />
          {running ? <Button variant="danger" onClick={() => cancelJob().catch(fail)}>취소</Button>
            : <Button variant="primary" onClick={start} disabled={!selected || !ordered.length}>실행 {ordered.length ? `(${ordered.length}단계)` : ""}</Button>}
        </div>
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
