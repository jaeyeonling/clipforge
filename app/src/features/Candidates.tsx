import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { REASONS, type Candidate } from "../api/types";
import { Button, Empty, Spinner, cx, fmtTime } from "../components/ui";
import { useApp } from "../state/store";

type Filter = "all" | "undecided" | "keep" | "no";

export function Candidates() {
  const { selected, tick, toast, fail } = useApp();
  const [items, setItems] = useState<Candidate[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!selected) { setItems([]); return; }
    try { setItems(await api.candidates(selected.id)); } catch (e) { fail(e); setItems([]); }
  }, [selected, fail]);
  useEffect(() => { load(); }, [load, tick]);

  const decide = async (c: Candidate, label: "keep" | "no", reason: string) => {
    if (!selected) return;
    const next = c.decision === label ? "" : label;              // 같은 버튼 다시 누르면 해제
    if (next === "no" && !reason) { toast("no 는 사유를 골라 주세요", true); return; }
    const key = `${c.start}-${c.end}`;
    setBusy(key);
    try {
      await api.decide(selected.id, c, next, next === "no" ? reason : "");
      toast(next ? `${next} 저장됨` : "판정 해제");
      setItems((cur) => cur?.map((x) => (x === c ? { ...x, decision: next, reason: next === "no" ? reason : "" } : x)) ?? cur);
    } catch (e) { fail(e); } finally { setBusy(null); }
  };

  if (!selected) return <Empty title="회차를 선택하세요" />;
  if (items === null) return <div className="row"><Spinner /> <span className="muted">후보 읽는 중…</span></div>;
  if (!items.length) return <Empty title="후보가 없습니다">파이프라인 탭에서 실행하면 순간 순위가 여기 뜹니다.</Empty>;

  const counts = { all: items.length, undecided: items.filter((c) => !c.decision).length, keep: items.filter((c) => c.decision === "keep").length, no: items.filter((c) => c.decision === "no").length };
  const shown = items.filter((c) => filter === "all" || (filter === "undecided" ? !c.decision : c.decision === filter));

  return (
    <>
      <div className="filters">
        {(["all", "undecided", "keep", "no"] as Filter[]).map((f) => (
          <Button key={f} variant="ghost" size="sm" className={cx(filter === f && "active")} onClick={() => setFilter(f)}>
            {{ all: "전체", undecided: "미판정", keep: "keep", no: "no" }[f]} {counts[f]}
          </Button>
        ))}
        <span className="muted xs" style={{ marginLeft: "auto" }}>재생해 보고 keep / no 를 누르면 정답(labels)으로 저장됩니다. no 는 사유가 필요합니다.</span>
      </div>
      <div className="cands">
        {shown.map((c) => <CandidateCard key={`${c.start}-${c.end}-${c.file}`} c={c} busy={busy === `${c.start}-${c.end}`} onDecide={decide} />)}
      </div>
    </>
  );
}

function CandidateCard({ c, busy, onDecide }: { c: Candidate; busy: boolean; onDecide: (c: Candidate, label: "keep" | "no", reason: string) => void }) {
  const [reason, setReason] = useState(c.reason || "");
  const ev = c.evidence || {};
  const len = Math.round(c.end - c.start);
  return (
    <article className={cx("cand", c.decision)}>
      {c.media_url ? <video src={c.media_url} controls preload="metadata" playsInline /> : <div className="novideo">초안 없음 (export 단계 미실행)</div>}
      <div className="body">
        <div className="rank"><span className="n">#{c.rank ?? "-"}</span><span>{c.variant}</span><span className="muted small">{fmtTime(c.start)}–{fmtTime(c.end)} · {len}s</span></div>
        {c.hook_lines?.length ? <div className="hook">{c.hook_lines.join(" / ")}</div> : null}
        <div className="meta">점수 {Number(c.score).toFixed(2)} · 앵커 {fmtTime(c.anchor)} {(ev.anchor_kinds || []).join("+")} · 컷 {ev.n_cuts ?? "-"} · 자막 {c.subtitle_cues ?? "-"}</div>
        <div className="dec">
          <Button size="sm" className={cx(c.decision === "keep" && "on-keep")} disabled={busy} onClick={() => onDecide(c, "keep", reason)} title="쓸 만함 (정답으로 저장)">keep</Button>
          <Button size="sm" className={cx(c.decision === "no" && "on-no")} disabled={busy} onClick={() => onDecide(c, "no", reason)} title="안 씀 (사유 선택)">no</Button>
          <select className="field sm" value={reason} onChange={(e) => setReason(e.target.value)} title="no 사유">
            <option value="">사유</option>{REASONS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
      </div>
    </article>
  );
}
