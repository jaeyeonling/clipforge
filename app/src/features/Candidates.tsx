import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { ANCHOR_LABEL, REASONS, VARIANT_LABEL, type Candidate, type EpisodePaths } from "../api/types";
import { inShell, shell } from "../shell";
import { TIP } from "../api/tips";
import { PreferenceLine } from "./Preference";
import { Button, Empty, Spinner, cx, fmtTime } from "../components/ui";
import { useApp } from "../state/store";

type Filter = "all" | "undecided" | "keep" | "no";
const keyOf = (c: Candidate) => `${c.start}-${c.end}`;
const isTyping = () => {
  const el = document.activeElement;
  return !!el && ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName);
};

/**
 * 후보 리뷰. 키보드: ← → 이동 · K keep · N 다음 1~6 으로 사유 선택(no) · Space 재생/정지 · C 비교에 담기(2개) · Esc 닫기
 * 판정은 labels.csv 에 바로 저장된다. 같은 버튼을 다시 누르면 해제.
 */
export function Candidates() {
  const { selected, tick, toast, fail, simple } = useApp();
  const [items, setItems] = useState<Candidate[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [paths, setPaths] = useState<EpisodePaths | null>(null);
  const [focusAt, setFocus] = useState(0);
  const [reasonPrompt, setReasonPrompt] = useState(false);
  const [compare, setCompare] = useState<string[]>([]); // keyOf 목록 (최대 2)
  const videos = useRef(new Map<string, HTMLVideoElement>());
  const keyMoved = useRef(false); // 다음 포커스 변경이 키보드에서 왔는가

  useEffect(() => {
    if (!selected) return; // 회차가 없으면 화면이 안내를 보여준다
    let stale = false; // 회차를 빨리 바꿔도 늦게 온 이전 회차의 응답이 화면을 덮지 않게
    api.candidates(selected.id).then(
      (c) => {
        if (!stale) setItems(c);
      },
      (e) => {
        if (stale) return;
        fail(e);
        setItems([]);
      },
    );
    return () => {
      stale = true;
    };
  }, [selected, tick, fail]);
  useEffect(() => {
    if (selected)
      api
        .episodePaths(selected.id)
        .then(setPaths)
        .catch(() => setPaths(null));
  }, [selected, tick]);
  // 회차가 바뀐 그 렌더에서 비교 · 포커스를 처음으로
  const [seenId, setSeenId] = useState(selected?.id);
  if (seenId !== selected?.id) {
    setSeenId(selected?.id);
    setCompare([]);
    setFocus(0);
  }
  const open = (p: string) => {
    if (shell) shell.shell.openPath(p).catch(fail);
    else {
      navigator.clipboard?.writeText(p).catch(() => {});
      toast(`경로를 복사했어요: ${p}`);
    }
  };

  const shown = useMemo(
    () =>
      (items || []).filter((c) => filter === "all" || (filter === "undecided" ? !c.decision : c.decision === filter)),
    [items, filter],
  );
  // 필터나 판정으로 목록이 줄어도 포커스는 목록 안에 (상태를 고치지 않고 읽을 때 자른다)
  const focus = Math.min(focusAt, Math.max(0, shown.length - 1));

  const decide = useCallback(
    async (c: Candidate, label: "keep" | "no", reason: string) => {
      if (!selected) return;
      const next = c.decision === label ? "" : label; // 같은 버튼 다시 누르면 해제
      if (next === "no" && !reason) {
        toast("안 쓰는 이유를 골라 주세요 (N 다음 1~6)", true);
        return;
      }
      setBusy(keyOf(c));
      try {
        await api.decide(selected.id, c, next, next === "no" ? reason : "");
        toast(
          next ? `${next === "keep" ? "쓸 만함" : "안 씀"} 저장됨${next === "no" ? " · " + reason : ""}` : "판정 취소",
        );
        setItems(
          (cur) =>
            cur?.map((x) =>
              keyOf(x) === keyOf(c) ? { ...x, decision: next, reason: next === "no" ? reason : "" } : x,
            ) ?? cur,
        );
      } catch (e) {
        fail(e);
      } finally {
        setBusy(null);
      }
    },
    [selected, toast, fail],
  );

  const toggleCompare = useCallback((c: Candidate) => {
    setCompare((cur) => (cur.includes(keyOf(c)) ? cur.filter((k) => k !== keyOf(c)) : [...cur.slice(-1), keyOf(c)]));
  }, []);

  // ---- 키보드 ----
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping() || !shown.length) return;
      const c = shown[focus];
      if (reasonPrompt) {
        if (/^[1-6]$/.test(e.key)) {
          e.preventDefault();
          setReasonPrompt(false);
          decide(c, "no", REASONS[Number(e.key) - 1]);
          return;
        }
        if (e.key === "Escape") {
          setReasonPrompt(false);
          return;
        }
      }
      switch (e.key) {
        case "ArrowRight":
        case "ArrowDown":
          e.preventDefault();
          keyMoved.current = true;
          setFocus(Math.min(shown.length - 1, focus + 1));
          break;
        case "ArrowLeft":
        case "ArrowUp":
          e.preventDefault();
          keyMoved.current = true;
          setFocus(Math.max(0, focus - 1));
          break;
        case "Home":
          e.preventDefault();
          keyMoved.current = true;
          setFocus(0);
          break;
        case "End":
          e.preventDefault();
          keyMoved.current = true;
          setFocus(shown.length - 1);
          break;
        case "k":
        case "K":
          e.preventDefault();
          decide(c, "keep", "");
          break;
        case "n":
        case "N":
          e.preventDefault();
          if (c.decision === "no") decide(c, "no", c.reason || "");
          else setReasonPrompt(true);
          break;
        case " ": {
          e.preventDefault();
          const v = videos.current.get(keyOf(c));
          if (v) {
            if (v.paused) v.play();
            else v.pause();
          }
          break;
        }
        case "c":
        case "C":
          e.preventDefault();
          toggleCompare(c);
          break;
        case "Escape":
          setCompare([]);
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [shown, focus, reasonPrompt, decide, toggleCompare]);

  useEffect(() => {
    // 키보드로 옮긴 포커스 카드만 보이게 스크롤한다 (탭을 열 때·클릭할 때는 화면을 움직이지 않는다)
    if (!keyMoved.current) return;
    keyMoved.current = false;
    const c = shown[focus];
    if (!c) return;
    document.querySelector<HTMLElement>(`[data-key="${keyOf(c)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [focus, shown]);

  if (!selected) return <Empty title="회차를 선택하세요" />;
  if (items === null)
    return (
      <div className="row">
        <Spinner /> <span className="muted">후보 읽는 중…</span>
      </div>
    );
  if (!items.length)
    return (
      <Empty title="아직 초안이 없어요">
        실행 탭에서 '쇼츠 초안 만들기'를 누르면 세로 초안이 순위대로 여기에 떠요.
      </Empty>
    );
  const outputs = paths && (
    <div className="outputs">
      <span className="muted xs" data-tip={TIP.outputs}>
        결과물
      </span>
      <Button
        size="sm"
        onClick={() => open(paths.shorts_dir.path)}
        disabled={!paths.shorts_dir.exists}
        title={paths.shorts_dir.path}
      >
        초안 폴더{paths.shorts_count ? ` (${paths.shorts_count})` : ""}
      </Button>
      <Button
        size="sm"
        onClick={() => open(paths.premiere_shorts.exists ? paths.premiere_shorts.path : paths.premiere_dir.path)}
        disabled={!paths.premiere_dir.exists}
        title={paths.premiere_shorts.path}
      >
        Premiere XML
      </Button>
      {!simple && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => open(paths.premiere_review.path)}
          disabled={!paths.premiere_review.exists}
          title="원본 전체 + 후보 트랙 + 마커 시퀀스"
        >
          리뷰 XML
        </Button>
      )}
      {paths.subtitles_srt?.exists && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => open(paths.subtitles_srt.path)}
          title={`영상 전체 자막 — ${paths.subtitles_srt.path}`}
        >
          자막 파일
        </Button>
      )}
      {paths.subtitles_vegas?.exists && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => open(paths.subtitles_vegas.path)}
          data-tip={TIP.subtitlesVegas}
        >
          베가스 자막
        </Button>
      )}
      {!inShell && <span className="muted xs">브라우저에서는 경로를 복사해요</span>}
    </div>
  );

  const counts = {
    all: items.length,
    undecided: items.filter((c) => !c.decision).length,
    keep: items.filter((c) => c.decision === "keep").length,
    no: items.filter((c) => c.decision === "no").length,
  };
  const cmpItems = compare.map((k) => items.find((c) => keyOf(c) === k)).filter((c): c is Candidate => !!c);

  return (
    <>
      {outputs}
      <PreferenceLine version={`${counts.keep}-${counts.no}`} />
      <div className="filters">
        {(["all", "undecided", "keep", "no"] as Filter[]).map((f) => (
          <Button
            key={f}
            variant="ghost"
            size="sm"
            className={cx(filter === f && "active")}
            onClick={() => {
              setFilter(f);
              setFocus(0);
            }}
          >
            {{ all: "전체", undecided: "아직 안 봄", keep: "쓸 만함", no: "안 씀" }[f]}{" "}
            <span className="count">{counts[f]}</span>
          </Button>
        ))}
        {!simple && (
          <span className="keys" title="키보드 단축키">
            <kbd>←</kbd>
            <kbd>→</kbd> 이동 · <kbd>K</kbd> 쓸 만함 · <kbd>N</kbd>+<kbd>1~6</kbd> 안 씀(사유) · <kbd>Space</kbd> 재생 ·{" "}
            <kbd>C</kbd> 비교 · <kbd>Esc</kbd> 닫기
          </span>
        )}
      </div>
      {reasonPrompt && shown[focus] && (
        <div className="sheet" role="dialog" aria-label="안 쓰는 이유">
          <h3>#{shown[focus].rank} 초안, 왜 안 쓰나요?</h3>
          <div className="sub">이유를 하나 골라 주세요. 판정과 함께 기록돼요. 숫자키로도 고를 수 있어요.</div>
          <div className="opts">
            {REASONS.map((r, i) => (
              <button
                key={r}
                className="btn"
                onClick={() => {
                  setReasonPrompt(false);
                  decide(shown[focus], "no", r);
                }}
              >
                <kbd>{i + 1}</kbd> {r}
              </button>
            ))}
          </div>
          <div className="foot">
            <Button size="sm" variant="ghost" onClick={() => setReasonPrompt(false)}>
              취소 (Esc)
            </Button>
          </div>
        </div>
      )}
      {cmpItems.length > 0 && (
        <ComparePanel items={cmpItems} onDecide={decide} onClose={() => setCompare([])} onRemove={toggleCompare} />
      )}
      <div className="cands">
        {shown.map((c, i) => (
          <CandidateCard
            key={keyOf(c)}
            c={c}
            focused={i === focus}
            inCompare={compare.includes(keyOf(c))}
            busy={busy === keyOf(c)}
            onFocus={() => setFocus(i)}
            onDecide={decide}
            onCompare={() => toggleCompare(c)}
            onAskReason={() => {
              setFocus(i);
              setReasonPrompt(true);
            }}
            videoRef={(el) => {
              if (el) videos.current.set(keyOf(c), el);
              else videos.current.delete(keyOf(c));
            }}
          />
        ))}
        {!shown.length && <Empty title="이 필터에 해당하는 후보가 없어요" />}
      </div>
    </>
  );
}

function CandidateCard({
  c,
  focused,
  inCompare,
  busy,
  onFocus,
  onDecide,
  onCompare,
  onAskReason,
  videoRef,
}: {
  c: Candidate;
  focused: boolean;
  inCompare: boolean;
  busy: boolean;
  onFocus: () => void;
  onDecide: (c: Candidate, label: "keep" | "no", reason: string) => void;
  onCompare: () => void;
  onAskReason: () => void;
  videoRef: (el: HTMLVideoElement | null) => void;
}) {
  const ev = c.evidence || {};
  const len = Math.round(c.end - c.start);
  return (
    <article
      className={cx("cand", c.decision, focused && "focused", inCompare && "in-compare")}
      data-key={keyOf(c)}
      onClick={onFocus}
      tabIndex={-1}
    >
      {c.media_url ? (
        <video ref={videoRef} src={c.media_url} controls preload="metadata" playsInline />
      ) : (
        <div className="novideo">초안 없음 (export 단계 미실행)</div>
      )}
      <div className="body">
        <div className="rank">
          <span className="n" data-tip="순위. 점수가 높은 순서.">
            #{c.rank ?? "-"}
          </span>
          <span data-tip={c.variant === "story" ? TIP.variantStory : TIP.variantShort}>
            {(VARIANT_LABEL[c.variant] || c.variant).split(" ")[0]}
          </span>
          <span className="muted small">
            {fmtTime(c.start)}–{fmtTime(c.end)} · {len}초
          </span>
          {c.gt && c.gt.length > 0 && (
            <span className="badge ok" title={`올린 쇼츠·확정본과 겹침: ${c.gt.join(", ")}`}>
              정답
            </span>
          )}
          <button
            className={cx("cmp", inCompare && "on")}
            data-tip={TIP.compare}
            onClick={(e) => {
              e.stopPropagation();
              onCompare();
            }}
          >
            ⇄
          </button>
        </div>
        {c.hook_lines?.length ? <div className="hook">{c.hook_lines.join(" / ")}</div> : null}
        <div className="meta">
          <span data-tip={TIP.score}>점수 {Number(c.score).toFixed(2)}</span> ·{" "}
          <span data-tip={TIP.anchor}>
            핵심 순간 {fmtTime(c.anchor)} {(ev.anchor_kinds || []).map((k) => ANCHOR_LABEL[k] || k).join("·")}
          </span>{" "}
          · <span data-tip={TIP.cuts}>컷 {ev.n_cuts ?? "-"}개</span> ·{" "}
          <span data-tip={TIP.subs}>자막 {c.subtitle_cues ?? "-"}줄</span>
        </div>
        <div className="dec">
          <Button
            className={cx(c.decision === "keep" && "on-keep")}
            disabled={busy}
            onClick={(e) => {
              e.stopPropagation();
              onDecide(c, "keep", "");
            }}
            data-tip={TIP.keep}
          >
            {c.decision === "keep" ? "✓ 쓸 만함" : "쓸 만함"}
          </Button>
          <Button
            className={cx(c.decision === "no" && "on-no")}
            disabled={busy}
            onClick={(e) => {
              e.stopPropagation();
              if (c.decision === "no") onDecide(c, "no", c.reason || "");
              else onAskReason();
            }}
            data-tip={TIP.no}
          >
            {c.decision === "no" ? "✓ 안 씀" : "안 씀"}
          </Button>
          {c.decision === "no" && c.reason && <span className="reason-chip">이유: {c.reason}</span>}
        </div>
      </div>
    </article>
  );
}

function ComparePanel({
  items,
  onDecide,
  onClose,
  onRemove,
}: {
  items: Candidate[];
  onDecide: (c: Candidate, label: "keep" | "no", reason: string) => void;
  onClose: () => void;
  onRemove: (c: Candidate) => void;
}) {
  const refs = useRef<(HTMLVideoElement | null)[]>([]);
  const playAll = () =>
    refs.current.forEach((v) => {
      if (v) {
        v.currentTime = 0;
        v.play().catch(() => {});
      }
    });
  const pauseAll = () => refs.current.forEach((v) => v?.pause());
  return (
    <section className="compare">
      <div className="compare-head">
        <b>비교</b>
        <span className="muted small">
          {items.length < 2
            ? "하나 더 담으면 나란히 봐요 (카드의 ⇄ 또는 C)"
            : "같은 순간을 두 번 자른 중복인지 확인하세요"}
        </span>
        <span style={{ flex: 1 }} />
        <Button size="sm" onClick={playAll}>
          둘 다 처음부터
        </Button>
        <Button size="sm" variant="ghost" onClick={pauseAll}>
          정지
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>
          닫기 (Esc)
        </Button>
      </div>
      <div className={cx("compare-grid", items.length === 1 && "one")}>
        {items.map((c, i) => (
          <div key={keyOf(c)} className={cx("compare-item", c.decision)}>
            {c.media_url ? (
              <video
                ref={(el) => {
                  refs.current[i] = el;
                }}
                data-group="compare"
                src={c.media_url}
                controls
                preload="metadata"
                playsInline
              />
            ) : (
              <div className="novideo">초안 없음</div>
            )}
            <div className="row between" style={{ marginTop: 6 }}>
              <span className="small">
                <b>#{c.rank}</b> {c.variant} · {fmtTime(c.start)}–{fmtTime(c.end)} · {Math.round(c.end - c.start)}s ·
                점수 {Number(c.score).toFixed(2)}
              </span>
              <span className="row">
                <Button
                  size="sm"
                  className={cx(c.decision === "keep" && "on-keep")}
                  onClick={() => onDecide(c, "keep", "")}
                >
                  쓸 만함
                </Button>
                <Button
                  size="sm"
                  className={cx(c.decision === "no" && "on-no")}
                  onClick={() => onDecide(c, "no", c.reason || "중복")}
                  title="이유: 중복"
                >
                  안 씀 (중복)
                </Button>
                <Button size="sm" variant="ghost" onClick={() => onRemove(c)}>
                  빼기
                </Button>
              </span>
            </div>
            {c.hook_lines?.length ? <div className="muted xs">{c.hook_lines.join(" / ")}</div> : null}
          </div>
        ))}
      </div>
    </section>
  );
}
