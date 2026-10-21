import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Job, MetricRow } from "../api/types";
import { STAGE_LABEL, type StageName } from "../api/types";
import { Badge, Button, Card, Empty, cx, fmtWhen } from "../components/ui";
import { TIP } from "../api/tips";
import { useApp } from "../state/store";
import { PreferenceCard } from "./Preference";

const STATUS_KO: Record<string, string> = {
  queued: "대기",
  running: "실행 중",
  done: "완료",
  error: "오류",
  cancelled: "취소",
};
const TONE: Record<string, string> = { done: "ok", error: "bad", running: "running", cancelled: "", queued: "" };

export function Metrics() {
  const { tick, fail } = useApp();
  const [rows, setRows] = useState<MetricRow[] | null>(null);
  useEffect(() => {
    api
      .metrics()
      .then(setRows)
      .catch((e) => {
        fail(e);
        setRows([]);
      });
  }, [tick, fail]);
  const pct = (v: number | null) => (v == null ? "-" : v);
  const shorts = (rows || []).filter((r) => r.phase === "shorts"),
    eps = (rows || []).filter((r) => r.phase === "editpoints");
  const avg = (xs: (number | null | undefined)[]) => {
    const v = xs.filter((x): x is number => typeof x === "number");
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  };
  const nLabels = shorts.reduce((a, r) => a + (r.labels || 0), 0),
    mrr = avg(shorts.map((r) => r.mrr));
  const recall = avg(eps.map((r) => r.recall)),
    coverage = avg(eps.map((r) => r.coverage));
  const Stat = ({
    v,
    unit,
    label,
    good,
  }: {
    v: number | null;
    unit?: string;
    label: string;
    good?: (x: number) => boolean;
  }) => (
    <div className={cx("stat", v != null && good && (good(v) ? "good" : "meh"))}>
      <div className="v">
        {v == null ? "–" : unit === "%" ? Math.round(v * 100) : v}
        {v != null && unit && <small>{unit}</small>}
      </div>
      <div className="l">{label}</div>
    </div>
  );
  return (
    <div className="two">
      <div>
        <Card title="쇼츠 — 순위가 얼마나 맞나">
          {shorts.length > 0 && (
            <div className="stats">
              <Stat v={nLabels} unit="개" label="지금까지 판정" />
              <Stat v={shorts.reduce((a, r) => a + (r.hit1 || 0), 0)} unit="개" label="정답이 1순위로 나온 횟수" />
              <Stat v={mrr} label="순위 점수 (MRR)" good={(x) => x >= 0.6} />
            </div>
          )}
          {rows === null ? (
            <span className="muted small">읽는 중…</span>
          ) : !rows.some((r) => r.phase === "shorts") ? (
            <Empty title="아직 판정한 회차가 없어요">
              쇼츠 초안 탭에서 쓸 만함 / 안 씀을 누르면 여기에 점수가 생겨요.
            </Empty>
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th>회차</th>
                  <th>판정 수</th>
                  <th>쓸 만함</th>
                  <th>안 씀</th>
                  <th data-tip={TIP.hit1}>
                    1위 적중 <span className="muted">hit@1</span>
                  </th>
                  <th data-tip={TIP.hit3}>
                    3위 안 <span className="muted">hit@3</span>
                  </th>
                  <th data-tip={TIP.mrr}>
                    순위 점수 <span className="muted">MRR</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows
                  .filter((r) => r.phase === "shorts")
                  .map((r) => (
                    <tr key={r.episode}>
                      <td>
                        <b>{r.episode}</b>
                      </td>
                      <td className="num">{r.labels}</td>
                      <td className="num">{r.keep}</td>
                      <td className="num">{r.no}</td>
                      <td className="num">{pct(r.hit1 ?? null)}</td>
                      <td className="num">{pct(r.hit3 ?? null)}</td>
                      <td className="num">{pct(r.mrr ?? null)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
          <p className="muted xs" style={{ marginTop: 10 }}>
            1위 적중 = 쓸 만하다고 한 구간이 1순위로 나온 비율 (hit@1), 순위 점수 = 평균 역순위 (MRR). 판정이 30개를
            넘기 전까지는 참고용이에요.
          </p>
        </Card>
        <Card title="편집 포인트 — 얼마나 찾고 얼마나 봐야 하나">
          {eps.length > 0 && (
            <div className="stats">
              <Stat v={recall} unit="%" label="정답 중 찾은 비율" good={(x) => x >= 0.95} />
              <Stat v={coverage} unit="%" label="원본 중 봐야 할 양" good={(x) => x <= 0.1} />
            </div>
          )}
          {rows === null ? (
            <span className="muted small">읽는 중…</span>
          ) : !rows.some((r) => r.phase === "editpoints") ? (
            <Empty title="정답이 있는 원본 회차가 없어요">
              원본 회차에 편집본을 넣어 정답을 만들거나, 편집 포인트 탭에서 '정답으로'를 누르면 생겨요.
            </Empty>
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th>회차</th>
                  <th>정답</th>
                  <th>후보</th>
                  <th data-tip={TIP.recall}>
                    찾은 비율 <span className="muted">recall</span>
                  </th>
                  <th data-tip={TIP.precision}>
                    맞춘 비율 <span className="muted">precision</span>
                  </th>
                  <th data-tip={TIP.coverage}>
                    검토량 <span className="muted">coverage</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows
                  .filter((r) => r.phase === "editpoints")
                  .map((r) => (
                    <tr key={r.episode}>
                      <td>
                        <b>{r.episode}</b>
                      </td>
                      <td className="num">{r.labels}</td>
                      <td className="num">{r.n_candidates}</td>
                      <td className="num">{((r.recall ?? 0) * 100).toFixed(0)}%</td>
                      <td className="num">{((r.precision ?? 0) * 100).toFixed(0)}%</td>
                      <td className="num">{((r.coverage ?? 0) * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
          <p className="muted xs" style={{ marginTop: 10 }}>
            목표: 찾은 비율(recall) 95% 이상, 검토량(coverage) 10% 이하. 놓친 정답은 편집 포인트 탭의 놓침 목록에서
            봐요.
          </p>
        </Card>
        <PreferenceCard version={tick} />
      </div>
      <Jobs />
    </div>
  );
}

export function Jobs() {
  const { jobs, viewJobId, viewJob, refreshJobs, fail } = useApp();
  const list = jobs.slice().reverse();
  return (
    <Card
      title="작업 이력"
      right={
        <Button variant="ghost" size="sm" onClick={() => refreshJobs().catch(fail)}>
          ↻
        </Button>
      }
    >
      {!list.length ? (
        <Empty title="아직 실행한 작업이 없어요" />
      ) : (
        <ul className="jobs">
          {list.map((j) => (
            <JobRow key={j.id} j={j} active={viewJobId === j.id} onClick={() => viewJob(j.id).catch(fail)} />
          ))}
        </ul>
      )}
      <p className="muted xs" style={{ marginTop: 10 }}>
        작업을 누르면 실행 탭의 기록 창에 그 작업의 기록이 열려요. 프로그램을 껐다 켜도 남아요.
      </p>
    </Card>
  );
}

function JobRow({ j, active, onClick }: { j: Job; active: boolean; onClick: () => void }) {
  const dur = j.finished && j.started ? Math.round(j.finished - j.started) : 0;
  const sd =
    j.stage_durations && Object.keys(j.stage_durations).length
      ? Object.entries(j.stage_durations)
          .map(([k, v]) => `${k} ${v}s`)
          .join(" · ")
      : "";
  return (
    <li
      className={cx("job", active && "active")}
      onClick={onClick}
      title={sd ? `단계별 소요: ${sd}` : "클릭하면 로그를 봐요"}
    >
      <Badge tone={TONE[j.status]}>{STATUS_KO[j.status] || j.status}</Badge>
      <span className="what">
        <b>{j.episode}</b>
        {j.status === "running"
          ? `${STAGE_LABEL[j.stage as StageName] || j.stage} ${Math.round(j.pct)}% · ${j.message}`
          : (j.stages || []).map((s) => STAGE_LABEL[s as StageName] || s).join(" → ")}
      </span>
      <span className="when">
        {fmtWhen(j.started)}
        {dur ? ` · ${dur}s` : ""}
      </span>
      {j.status === "error" && j.error && <span className="err">{j.error}</span>}
    </li>
  );
}
