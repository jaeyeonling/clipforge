import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Job, MetricRow } from "../api/types";
import { Badge, Button, Card, Empty, cx, fmtWhen } from "../components/ui";
import { useApp } from "../state/store";

const STATUS_KO: Record<string, string> = { queued: "대기", running: "실행 중", done: "완료", error: "오류", cancelled: "취소" };
const TONE: Record<string, string> = { done: "ok", error: "bad", running: "running", cancelled: "", queued: "" };

export function Metrics() {
  const { tick, fail } = useApp();
  const [rows, setRows] = useState<MetricRow[] | null>(null);
  useEffect(() => { api.metrics().then(setRows).catch((e) => { fail(e); setRows([]); }); }, [tick, fail]);
  const pct = (v: number | null) => (v == null ? "-" : v);
  return (
    <div className="two">
      <div>
        <Card title="쇼츠 지표 (hit@K · MRR)">
          {rows === null ? <span className="muted small">읽는 중…</span> : !rows.some((r) => r.phase === "shorts") ? <Empty title="라벨이 있는 편집본 회차가 없습니다">후보 탭에서 keep / no 를 누르면 여기 지표가 생깁니다.</Empty> : (
            <table className="data">
              <thead><tr><th>회차</th><th>라벨</th><th>keep</th><th>no</th><th>hit@1</th><th>hit@3</th><th>MRR</th></tr></thead>
              <tbody>{rows.filter((r) => r.phase === "shorts").map((r) => (
                <tr key={r.episode}><td><b>{r.episode}</b></td><td className="num">{r.labels}</td><td className="num">{r.keep}</td><td className="num">{r.no}</td><td className="num">{pct(r.hit1 ?? null)}</td><td className="num">{pct(r.hit3 ?? null)}</td><td className="num">{pct(r.mrr ?? null)}</td></tr>
              ))}</tbody>
            </table>
          )}
          <p className="muted xs" style={{ marginTop: 10 }}>hit@K = 정답 구간이 상위 K 안에 든 비율. 라벨이 30개를 넘기 전까지는 참고용입니다.</p>
        </Card>
        <Card title="편집 포인트 지표 (recall · coverage)">
          {rows === null ? <span className="muted small">읽는 중…</span> : !rows.some((r) => r.phase === "editpoints") ? <Empty title="정답이 있는 원본 회차가 없습니다">원본 회차에 align(최종본 정렬)을 돌리거나 편집 포인트 탭에서 kept 를 표시하면 생깁니다.</Empty> : (
            <table className="data">
              <thead><tr><th>회차</th><th>정답</th><th>후보</th><th>recall</th><th>precision</th><th>coverage</th></tr></thead>
              <tbody>{rows.filter((r) => r.phase === "editpoints").map((r) => (
                <tr key={r.episode}><td><b>{r.episode}</b></td><td className="num">{r.labels}</td><td className="num">{r.n_candidates}</td><td className="num">{((r.recall ?? 0) * 100).toFixed(0)}%</td><td className="num">{((r.precision ?? 0) * 100).toFixed(0)}%</td><td className="num">{((r.coverage ?? 0) * 100).toFixed(1)}%</td></tr>
              ))}</tbody>
            </table>
          )}
          <p className="muted xs" style={{ marginTop: 10 }}>목표: recall ≥ 95%, coverage ≤ 10%. recall 이 1순위 — 놓친 정답은 편집 포인트 탭 "정답 아님" 필터와 지표 카드의 놓침 목록에서 봅니다.</p>
        </Card>
      </div>
      <Jobs />
    </div>
  );
}

export function Jobs() {
  const { jobs, viewJobId, viewJob, refreshJobs, fail } = useApp();
  const list = jobs.slice().reverse();
  return (
    <Card title="작업 이력" right={<Button variant="ghost" size="sm" onClick={() => refreshJobs().catch(fail)}>↻</Button>}>
      {!list.length ? <Empty title="아직 실행한 작업이 없습니다" /> : (
        <ul className="jobs">
          {list.map((j) => <JobRow key={j.id} j={j} active={viewJobId === j.id} onClick={() => viewJob(j.id).catch(fail)} />)}
        </ul>
      )}
      <p className="muted xs" style={{ marginTop: 10 }}>작업을 누르면 파이프라인 탭의 로그 창에 그 작업의 로그가 열립니다. 엔진을 재시작해도 매니페스트로 이력이 남습니다.</p>
    </Card>
  );
}

function JobRow({ j, active, onClick }: { j: Job; active: boolean; onClick: () => void }) {
  const dur = j.finished && j.started ? Math.round(j.finished - j.started) : 0;
  const sd = j.stage_durations && Object.keys(j.stage_durations).length ? Object.entries(j.stage_durations).map(([k, v]) => `${k} ${v}s`).join(" · ") : "";
  return (
    <li className={cx("job", active && "active")} onClick={onClick} title={sd ? `단계별 소요: ${sd}` : "클릭하면 로그를 봅니다"}>
      <Badge tone={TONE[j.status]}>{STATUS_KO[j.status] || j.status}</Badge>
      <span className="what"><b>{j.episode}</b>{j.status === "running" ? `${j.stage} ${Math.round(j.pct)}% · ${j.message}` : (j.stages || []).join(" → ")}</span>
      <span className="when">{fmtWhen(j.started)}{dur ? ` · ${dur}s` : ""}</span>
      {j.status === "error" && j.error && <span className="err">{j.error}</span>}
    </li>
  );
}
