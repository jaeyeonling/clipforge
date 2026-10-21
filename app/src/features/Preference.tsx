import { useEffect, useState } from "react";
import { api } from "../api/client";
import { TIP } from "../api/tips";
import { PREF_AXIS_LABEL, type PrefAxis, type Preference } from "../api/types";
import { Card } from "../components/ui";

/** 판정 학습 상태를 읽는다. version 이 바뀌면(판정 수가 바뀌면) 다시 읽는다. */
export function usePreference(version: unknown): Preference | null {
  const [pref, setPref] = useState<Preference | null>(null);
  useEffect(() => {
    let alive = true;
    api
      .preference()
      .then((p) => alive && setPref(p))
      .catch(() => alive && setPref(null));
    return () => {
      alive = false;
    };
  }, [version]);
  return pref;
}

/** 판정이 순위에 반영되는지 한 줄로. 아직이면 몇 개가 더 필요한지 말한다. */
export function preferenceSentence(p: Preference): string {
  const n = p.n_keep + p.n_no;
  if (p.learned) return `판정 ${n}개를 반영해 순위를 매기고 있어요`;
  if (n === 0) return "쓸 만함 / 안 씀을 누를수록 다음 초안부터 순위가 취향에 맞춰져요";
  return p.reason;
}

export function PreferenceLine({ version }: { version: unknown }) {
  const p = usePreference(version);
  if (!p) return null;
  return (
    <div className="pref-line" data-tip={TIP.preference}>
      <span className={p.learned ? "dot on" : "dot"} />
      {preferenceSentence(p)}
    </div>
  );
}

const AXES: PrefAxis[] = ["payoff", "reaction", "chat", "completeness", "hook"];

/** 기록 탭: 축마다 기본 가중치와 지금 쓰는 가중치를 나란히. */
export function PreferenceCard({ version }: { version: unknown }) {
  const p = usePreference(version);
  if (!p) return null;
  const max = Math.max(...AXES.map((a) => Math.max(p.weights[a], p.default[a])), 0.01);
  return (
    <Card title={<span data-tip={TIP.preference}>판정 반영 — 무엇을 보고 순위를 매기나</span>}>
      <div className="stats">
        <div className="stat">
          <div className="v">
            {p.n_keep}
            <small>개</small>
          </div>
          <div className="l">쓸 만함</div>
        </div>
        <div className="stat">
          <div className="v">
            {p.n_no}
            <small>개</small>
          </div>
          <div className="l">안 씀</div>
        </div>
        <div className={p.learned ? "stat good" : "stat"}>
          <div className="v">
            {Math.round(p.blend * 100)}
            <small>%</small>
          </div>
          <div className="l">판정이 섞인 비율</div>
        </div>
      </div>
      <ul className="pref-bars">
        {AXES.map((a) => (
          <li key={a}>
            <span className="name">{PREF_AXIS_LABEL[a]}</span>
            <span className="bars">
              <i className="base" style={{ width: `${(100 * p.default[a]) / max}%` }} />
              <i className="now" style={{ width: `${(100 * p.weights[a]) / max}%` }} />
            </span>
            <span className="num">
              {Math.round(p.weights[a] * 100)}
              {p.learned && p.weights[a] !== p.default[a] && (
                <small>
                  {p.weights[a] > p.default[a] ? " ▲" : " ▼"}
                  {Math.abs(Math.round((p.weights[a] - p.default[a]) * 100))}
                </small>
              )}
            </span>
          </li>
        ))}
      </ul>
      <p className="muted xs" style={{ marginTop: 10 }}>
        {preferenceSentence(p)}. 회색 막대는 기본값, 파란 막대는 지금 쓰는 값이에요. 판정이 적을 때는 기본값에서 조금만
        움직여요.
      </p>
    </Card>
  );
}
