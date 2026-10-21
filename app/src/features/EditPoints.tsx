import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { EditPointsResult, KeptSeg, LabelCategory } from "../api/types";
import { Badge, Button, Card, Empty, Spinner, cx, fmtTime } from "../components/ui";
import { useApp } from "../state/store";
import { TIP } from "../api/tips";

/**
 * Phase 2: 원본 → 편집 포인트.
 *   왼쪽: 원본 플레이어 · 정답 구간(align 결과 + 직접 추가)에 범주 붙이기 · 범주별 recall
 *   오른쪽: 후보 목록(정답 겹침 표시) · kept/no 판정
 * 키보드(후보): ↑↓ 이동 · Enter 2초 전부터 재생 · K kept · N no · Esc 정지
 * 키보드(정답): ↑↓ 이동 · Enter 재생 · 1~6 범주 · Delete 삭제 · I/O 현재 위치를 시작/끝으로 · A 구간 추가 · Tab 패널 전환
 */
export function EditPoints() {
  const { selected, tick, toast, fail } = useApp();
  const [data, setData] = useState<EditPointsResult | null>(null);
  const [kept, setKept] = useState<KeptSeg[]>([]);
  const [cats, setCats] = useState<LabelCategory[]>([]);
  const [pane, setPane] = useState<"cands" | "kept">("cands");
  const [focus, setFocus] = useState(0);
  const [kfocus, setKfocus] = useState(0);
  const [filter, setFilter] = useState<"all" | "missed" | "undecided">("all");
  const [mark, setMark] = useState<{ in: number | null; out: number | null }>({ in: null, out: null });
  const [addCat, setAddCat] = useState("kept");
  const video = useRef<HTMLVideoElement>(null);

  const load = useCallback(async () => {
    if (!selected) {
      setData(null);
      setKept([]);
      return;
    }
    try {
      const [d, k] = await Promise.all([api.editpoints(selected.id), api.kept(selected.id)]);
      setData(d);
      setKept(k.kept);
      setCats(k.categories);
    } catch (e) {
      fail(e);
      setData(null);
    }
  }, [selected, fail]);
  useEffect(() => {
    load();
  }, [load, tick]);
  useEffect(() => {
    setFocus(0);
    setKfocus(0);
    setMark({ in: null, out: null });
  }, [selected?.id, filter]);

  const rows = useMemo(
    () => (data?.candidates || []).filter((c) => filter === "all" || (filter === "undecided" ? !c.decision : !c.kept)),
    [data, filter],
  );
  const catOf = useCallback((key: string) => cats.find((c) => c.key === key), [cats]);
  const seek = useCallback((t: number, play = true) => {
    const v = video.current;
    if (!v) return;
    v.currentTime = Math.max(0, t);
    if (play) v.play().catch(() => {});
  }, []);
  const now = () => video.current?.currentTime ?? 0;

  const decide = useCallback(
    async (idx: number, label: "kept" | "no") => {
      const c = data?.candidates[idx];
      if (!c || !selected) return;
      const next = c.decision === label ? "" : label;
      try {
        await api.decideEditPoint(selected.id, c.start, c.end, next);
        toast(next ? `${next === "kept" ? "정답으로" : "아님으로"} 저장됨` : "판정 취소");
        await load();
      } catch (e) {
        fail(e);
      }
    },
    [data, selected, toast, fail, load],
  );
  const setCat = useCallback(
    async (k: KeptSeg, key: string) => {
      if (!selected) return;
      const next = k.label === key ? "kept" : key;
      try {
        await api.keptSet(selected.id, k.start, k.end, next);
        await load();
      } catch (e) {
        fail(e);
      }
    },
    [selected, load, fail],
  );
  const del = useCallback(
    async (k: KeptSeg) => {
      if (!selected) return;
      try {
        await api.keptDelete(selected.id, k.start, k.end);
        toast("정답 구간 삭제");
        await load();
      } catch (e) {
        fail(e);
      }
    },
    [selected, load, fail, toast],
  );
  const addRange = useCallback(async () => {
    if (!selected) return;
    const a = mark.in,
      b = mark.out;
    if (a == null || b == null || b <= a) {
      toast("I 로 시작, O 로 끝을 먼저 찍으세요 (재생 위치 기준)", true);
      return;
    }
    try {
      await api.keptAdd(selected.id, a, b, addCat, "ui");
      toast(`정답 구간 추가 ${fmtTime(a)}–${fmtTime(b)}`);
      setMark({ in: null, out: null });
      await load();
    } catch (e) {
      fail(e);
    }
  }, [selected, mark, addCat, toast, fail, load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement;
      if (el && ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName)) return;
      if (e.key === "Tab") {
        e.preventDefault();
        setPane((p) => (p === "cands" ? "kept" : "cands"));
        return;
      }
      if (e.key === "Escape") {
        video.current?.pause();
        return;
      }
      if (e.key === "i" || e.key === "I") {
        e.preventDefault();
        setMark((m) => ({ ...m, in: now() }));
        return;
      }
      if (e.key === "o" || e.key === "O") {
        e.preventDefault();
        setMark((m) => ({ ...m, out: now() }));
        return;
      }
      if (e.key === "a" || e.key === "A") {
        e.preventDefault();
        addRange();
        return;
      }
      if (pane === "kept") {
        const k = kept[kfocus];
        if (!kept.length) return;
        switch (e.key) {
          case "ArrowDown":
          case "ArrowRight":
            e.preventDefault();
            setKfocus((i) => Math.min(kept.length - 1, i + 1));
            break;
          case "ArrowUp":
          case "ArrowLeft":
            e.preventDefault();
            setKfocus((i) => Math.max(0, i - 1));
            break;
          case "Enter":
            e.preventDefault();
            if (k) seek(k.start - 1);
            break;
          case "Delete":
          case "Backspace":
            e.preventDefault();
            if (k) del(k);
            break;
          default: {
            const c = cats.find((x) => x.shortcut === e.key);
            if (c && k) {
              e.preventDefault();
              setCat(k, c.key);
            }
          }
        }
        return;
      }
      if (!rows.length) return;
      const c = rows[focus];
      switch (e.key) {
        case "ArrowDown":
        case "ArrowRight":
          e.preventDefault();
          setFocus((i) => Math.min(rows.length - 1, i + 1));
          break;
        case "ArrowUp":
        case "ArrowLeft":
          e.preventDefault();
          setFocus((i) => Math.max(0, i - 1));
          break;
        case "Enter":
          e.preventDefault();
          seek(c.start - 2);
          break;
        case "k":
        case "K":
          e.preventDefault();
          decide(c.idx, "kept");
          break;
        case "n":
        case "N":
          e.preventDefault();
          decide(c.idx, "no");
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pane, rows, focus, kept, kfocus, cats, seek, decide, setCat, del, addRange]);

  if (!selected) return <Empty title="회차를 선택하세요" />;
  if (!data)
    return (
      <div className="row">
        <Spinner /> <span className="muted">편집 포인트 읽는 중…</span>
      </div>
    );
  if (!data.candidates.length && !kept.length)
    return (
      <Empty title="아직 편집 포인트가 없어요">
        실행 탭에서 '편집 포인트 뽑기'를 누르면 후보가 여기에 떠요. 편집본을 같이 넣으면 정답을 자동으로 만들어 얼마나
        찾았는지도 보여줘요.
      </Empty>
    );

  const rep = data.report;
  const al = data.align;
  const total = data.candidates.reduce((a, c) => a + (c.end - c.start), 0);
  const unlabeled = kept.filter((k) => k.label === "kept").length;
  return (
    <div className="ep-layout">
      <div>
        <Card
          title="원본 재생"
          right={
            <span className="muted xs">
              {fmtTime(data.duration)} · 후보 {data.candidates.length}개 · 검토량 {fmtTime(total)} (
              {data.duration ? Math.round((100 * total) / data.duration) : 0}%)
            </span>
          }
        >
          {data.video_url ? (
            <video ref={video} className="ep-video" src={data.video_url} controls preload="metadata" />
          ) : (
            <div className="novideo" style={{ aspectRatio: "16/9" }}>
              영상 파일을 찾을 수 없어요
            </div>
          )}
          <div className="row small" style={{ marginTop: 8, gap: 10 }}>
            <span className="keys">
              <kbd>Tab</kbd> 패널 전환 · <kbd>I</kbd>/<kbd>O</kbd> 시작/끝 찍기 · <kbd>A</kbd> 구간 추가 ·{" "}
              <kbd>Esc</kbd> 정지
            </span>
            <span className="grow" style={{ flex: 1 }} />
            <span className="mono xs muted">
              IN {mark.in == null ? "–" : fmtTime(mark.in)} · OUT {mark.out == null ? "–" : fmtTime(mark.out)}
            </span>
            <select
              className="field sm"
              value={addCat}
              onChange={(e) => setAddCat(e.target.value)}
              data-tip="추가할 구간의 종류"
            >
              <option value="kept">종류 없음</option>
              {cats.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label}
                </option>
              ))}
            </select>
            <Button size="sm" onClick={addRange} disabled={mark.in == null || mark.out == null}>
              구간 추가
            </Button>
          </div>
        </Card>

        <Card
          title={
            <span
              data-tip={TIP.category}
            >{`정답 구간 · ${kept.length}개${unlabeled ? ` (종류 없음 ${unlabeled})` : ""}`}</span>
          }
          className={cx(pane === "kept" && "pane-active")}
          right={
            <span className="keys">
              <kbd>↑</kbd>
              <kbd>↓</kbd> 이동 · <kbd>1</kbd>~<kbd>{cats.length}</kbd> 종류 · <kbd>Enter</kbd> 재생 · <kbd>Del</kbd>{" "}
              삭제
            </span>
          }
        >
          {!kept.length ? (
            <p className="muted small">
              아직 정답이 없어요. 파이프라인에서 최종본 파일로 align 을 돌리거나, 재생하면서 I/O 로 구간을 찍어
              추가하세요.
            </p>
          ) : (
            <ul className="kept-list" onClick={() => setPane("kept")}>
              {kept.map((k, i) => {
                const c = catOf(k.label);
                return (
                  <li
                    key={`${k.start}-${k.end}`}
                    className={cx("kept-row", pane === "kept" && i === kfocus && "focused")}
                    onClick={() => {
                      setKfocus(i);
                      setPane("kept");
                    }}
                    onDoubleClick={() => seek(k.start - 1)}
                  >
                    <span className="t mono">
                      {fmtTime(k.start)}–{fmtTime(k.end)}
                    </span>
                    <span className="d muted xs">{Math.round(k.end - k.start)}s</span>
                    <span className="src">
                      <Badge tone={k.source === "auto" ? "ok" : ""} title={k.note}>
                        {k.source === "auto" ? "자동(편집본)" : k.source === "ui" ? "판정" : "직접"}
                      </Badge>
                    </span>
                    <span className="cats">
                      {cats.map((cat) => (
                        <button
                          key={cat.key}
                          className={cx("cat", k.label === cat.key && "on")}
                          style={{ "--cat": cat.color } as React.CSSProperties}
                          title={`${cat.hint || ""} (${cat.shortcut})`}
                          onClick={(e) => {
                            e.stopPropagation();
                            setKfocus(i);
                            setPane("kept");
                            setCat(k, cat.key);
                          }}
                        >
                          {cat.label}
                        </button>
                      ))}
                    </span>
                    <span className="btns">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          seek(k.start - 1);
                        }}
                        title="1초 전부터 재생"
                      >
                        ▶
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          del(k);
                        }}
                        title="정답에서 제거"
                      >
                        ✕
                      </Button>
                    </span>
                    {c && <i className="catbar" style={{ background: c.color }} />}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Card title="지표">
          {rep ? (
            <>
              <table className="data">
                <tbody>
                  <tr>
                    <td data-tip={TIP.recall}>
                      찾은 비율 <span className="muted">(recall)</span>
                    </td>
                    <td className="num">{(rep.recall * 100).toFixed(0)}%</td>
                    <td className="muted xs">정답 {rep.n_labels}개 중 후보가 잡은 비율 (recall) — 가장 중요</td>
                  </tr>
                  <tr>
                    <td data-tip={TIP.coverage}>
                      검토량 <span className="muted">(coverage)</span>
                    </td>
                    <td className="num">{(rep.coverage * 100).toFixed(1)}%</td>
                    <td className="muted xs">사람이 봐야 할 영상 비율 (coverage, 목표 10% 이하)</td>
                  </tr>
                  <tr>
                    <td data-tip={TIP.precision}>
                      맞춘 비율 <span className="muted">(precision)</span>
                    </td>
                    <td className="num">{(rep.precision * 100).toFixed(0)}%</td>
                    <td className="muted xs">후보 중 정답과 겹친 비율 (precision)</td>
                  </tr>
                  <tr>
                    <td>놓침</td>
                    <td className="num">{rep.missed.length}</td>
                    <td className="muted xs">
                      {rep.missed
                        .slice(0, 6)
                        .map((m) => `${fmtTime(m.start)}–${fmtTime(m.end)}`)
                        .join(", ")}
                      {rep.missed.length > 6 ? " …" : ""}
                    </td>
                  </tr>
                </tbody>
              </table>
              {Object.keys(rep.by_label).length > 0 && (
                <div className="bylabel">
                  {Object.entries(rep.by_label).map(([lab, v]) => {
                    const c = catOf(lab);
                    const r = v.total ? v.hit / v.total : 0;
                    return (
                      <div key={lab} className="bl">
                        <span className="name" style={{ color: c?.color }}>
                          {c?.label || lab}
                        </span>
                        <div className="bar">
                          <i style={{ width: `${r * 100}%`, background: c?.color || "var(--ok)" }} />
                        </div>
                        <span className="mono xs">
                          {v.hit}/{v.total}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
              <p className="muted xs" style={{ marginTop: 8 }}>
                찾은 비율이 낮은 종류가 다음에 보강할 신호를 알려줘요 (예: 득템이 낮으면 배너·드랍음, 리액션이 낮으면
                음량·발화).
              </p>
            </>
          ) : (
            <p className="muted small">
              정답(kept)이 아직 없어요. 파이프라인에서 최종본 파일을 지정해 align 을 실행하거나, 위에서 직접 구간을
              추가하세요.
            </p>
          )}
          {al && (
            <p className="muted xs" style={{ marginTop: 8 }}>
              align: 최종본 {al.final} 의 {Math.round((al.matched_frac || 0) * 100)}% 매칭, {al.n_segments}구간
              {al.unmatched?.length ? ` · 미매칭 ${al.unmatched.length}곳(인트로·카드)` : ""}
            </p>
          )}
          {data.signals.length > 0 && (
            <p className="muted xs" style={{ marginTop: 4 }}>
              신호: {data.signals.join(", ")}
            </p>
          )}
        </Card>
      </div>

      <Card
        title="후보"
        className={cx(pane === "cands" && "pane-active")}
        right={
          <span className="row">
            {(["all", "missed", "undecided"] as const).map((f) => (
              <Button
                key={f}
                size="sm"
                variant="ghost"
                className={cx(filter === f && "active")}
                onClick={() => setFilter(f)}
              >
                {{ all: "전체", missed: "정답과 안 겹침", undecided: "아직 안 봄" }[f]}
              </Button>
            ))}
          </span>
        }
      >
        <div className="keys" style={{ marginBottom: 6 }}>
          <kbd>↑</kbd>
          <kbd>↓</kbd> 이동 · <kbd>Enter</kbd> 2초 전부터 재생 · <kbd>K</kbd> 정답으로 · <kbd>N</kbd> 아님
        </div>
        <ul className="ep-list" onClick={() => setPane("cands")}>
          {rows.map((c, i) => (
            <li
              key={c.idx}
              className={cx("ep-row", pane === "cands" && i === focus && "focused", c.kept && "kept", c.decision)}
              onClick={() => {
                setFocus(i);
                setPane("cands");
                seek(c.start - 2);
              }}
            >
              <span className="t mono">
                {fmtTime(c.start)}–{fmtTime(c.end)}
              </span>
              <span className="d muted xs">{Math.round(c.end - c.start)}s</span>
              <span className="s mono">{c.score.toFixed(2)}</span>
              <span className="tags">
                {c.kept && (
                  <Badge tone="ok" title={c.kept_labels.join(", ")}>
                    {c.kept_labels.map((l) => catOf(l)?.label || l).join("·") || "정답"}
                  </Badge>
                )}
                {c.decision && (
                  <Badge tone={c.decision === "kept" ? "ok" : "bad"}>{c.decision === "kept" ? "정답" : "아님"}</Badge>
                )}
              </span>
              <span className="btns">
                <Button
                  size="sm"
                  className={cx(c.decision === "kept" && "on-keep")}
                  onClick={(e) => {
                    e.stopPropagation();
                    decide(c.idx, "kept");
                  }}
                  data-tip={TIP.kept}
                >
                  정답으로
                </Button>
                <Button
                  size="sm"
                  className={cx(c.decision === "no" && "on-no")}
                  onClick={(e) => {
                    e.stopPropagation();
                    decide(c.idx, "no");
                  }}
                  data-tip={TIP.notKept}
                >
                  아님
                </Button>
              </span>
            </li>
          ))}
          {!rows.length && (
            <li className="muted small" style={{ padding: 10 }}>
              이 필터에 해당하는 후보가 없어요
            </li>
          )}
        </ul>
      </Card>
    </div>
  );
}
