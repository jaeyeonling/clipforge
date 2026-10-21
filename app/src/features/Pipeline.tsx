import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import {
  DEFAULT_STAGES,
  KIND_LABEL,
  STAGES,
  STAGE_LABEL,
  STAGE_TECH,
  type EpisodeKind,
  type EpisodePaths,
  type Layout,
  type StageName,
} from "../api/types";
import { Badge, Button, Card, Progress, Spinner, cx, fmtDur } from "../components/ui";
import { inShell, shell } from "../shell";
import { STAGE_TIP, TIP } from "../api/tips";
import { isAnalyzed, quickRunStages, subtitleRunStages } from "../api/plan";
import { useApp } from "../state/store";

const PRESETS: { key: string; label: string; title: string; kinds: EpisodeKind[]; stages: StageName[] }[] = [
  {
    key: "full",
    label: "처음부터 전부",
    title: "처음 처리하는 회차: 영상 읽기부터 결과까지",
    kinds: ["edited", "original"],
    stages: [],
  },
  {
    key: "rank",
    label: "초안만 다시",
    title: "이미 읽어 둔 결과로 쇼츠 후보·세로 초안·Premiere 파일·점수만 다시",
    kinds: ["edited"],
    stages: ["shorts", "export", "xml", "eval"],
  },
  {
    key: "points",
    label: "포인트만 다시",
    title: "이미 읽어 둔 신호로 편집 포인트·점수만 다시",
    kinds: ["original"],
    stages: ["candidates", "eval"],
  },
  {
    key: "eval",
    label: "점수만",
    title: "판정이 바뀐 뒤 점수만 다시 매김",
    kinds: ["edited", "original"],
    stages: ["eval"],
  },
];
const STATUS_KO: Record<string, string> = {
  queued: "대기",
  running: "실행 중",
  done: "완료",
  error: "오류",
  cancelled: "취소",
};
/** 회차 종류별로 보여줄 단계 (다른 종류의 단계는 숨긴다) */
const STAGES_FOR: Record<EpisodeKind, StageName[]> = {
  edited: ["prep", "transcribe", "subtitles", "signals", "shorts", "export", "xml", "align", "weaklabel", "eval"],
  original: ["prep", "transcribe", "subtitles", "signals", "candidates", "align", "xml", "eval"],
};

export function Pipeline() {
  const { selected, activeJob, runJob, cancelJob, fail, runError, dismissError, toast, lastDone, simple, tick } =
    useApp();
  const kind: EpisodeKind = selected?.kind || "edited";
  const [stages, setStages] = useState<Set<StageName>>(new Set(DEFAULT_STAGES.edited));
  const [layout, setLayout] = useState<Layout>("card");
  const [k, setK] = useState(5);
  const [force, setForce] = useState(false);
  const [finalPath, setFinalPath] = useState("");
  const [shortsPaths, setShortsPaths] = useState<string[]>([]);
  const [threshold, setThreshold] = useState(1.5);
  const lastKind = useRef<EpisodeKind | null>(null);
  useEffect(() => {
    if (lastKind.current !== kind) {
      lastKind.current = kind;
      setStages(new Set(DEFAULT_STAGES[kind]));
    }
  }, [kind]);

  const running = !!activeJob && (activeJob.status === "running" || activeJob.status === "queued");
  const [, tickNow] = useState(0);
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => tickNow((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [running]); // 경과 시간·ETA 가 1초마다 움직이게
  const visible = STAGES_FOR[kind];
  const toggle = (s: StageName) =>
    setStages((cur) => {
      const n = new Set(cur);
      if (n.has(s)) n.delete(s);
      else n.add(s);
      return n;
    });
  const ordered = STAGES.filter((s) => stages.has(s) && visible.includes(s));
  const needsFinal = ordered.includes("align") && kind === "original";
  const needsShorts = ordered.includes("align") && kind === "edited";

  // 결과물 위치 (단순 모드의 '초안 보러 가기' · '자막 파일 열기')
  const [paths, setPaths] = useState<EpisodePaths | null>(null);
  useEffect(() => {
    if (selected)
      api
        .episodePaths(selected.id)
        .then(setPaths)
        .catch(() => setPaths(null));
    else setPaths(null);
  }, [selected?.id, tick, lastDone]); // eslint-disable-line react-hooks/exhaustive-deps
  const openPath = (p: string) => {
    if (shell) shell.shell.openPath(p).catch(fail);
    else {
      navigator.clipboard?.writeText(p).catch(() => {});
      toast(`경로를 복사했어요: ${p}`);
    }
  };

  const pickFinal = async () => {
    if (!shell) return;
    try {
      const ps = await shell.shell.pickVideos();
      if (ps[0]) setFinalPath(ps[0]);
    } catch (e) {
      fail(e);
    }
  };
  const pickShorts = async () => {
    if (!shell) return;
    try {
      const ps = await shell.shell.pickVideos();
      if (ps.length) setShortsPaths((cur) => [...new Set([...cur, ...ps])]);
    } catch (e) {
      fail(e);
    }
  };
  const start = async () => {
    if (!selected) return;
    if (!ordered.length) return fail(new Error("단계를 하나 이상 선택하세요"));
    if (needsFinal && !finalPath.trim()) {
      toast("편집본 파일을 골라 주세요. 원본의 어느 구간이 살아남았는지 맞춰 보려면 필요해요", true);
      return;
    }
    if (needsShorts && !shortsPaths.length) {
      toast("쇼츠 파일을 골라 주세요. 이 회차에서 잘라 올린 쇼츠를 주면 정답으로 기록해요", true);
      return;
    }
    try {
      await runJob(selected.id, ordered, {
        layout,
        k,
        force,
        kind,
        threshold,
        final: needsFinal ? finalPath.trim() : undefined,
        shorts: needsShorts ? shortsPaths : undefined,
      });
    } catch (e) {
      fail(e);
    }
  };
  const retry = async () => {
    const j = runError?.job;
    if (!j) return;
    const p = j.params as Record<string, unknown>;
    try {
      await runJob(j.episode, j.stages, {
        layout: (p.layout as Layout) || "card",
        k: Number(p.k) || 5,
        force: !!p.force,
        kind: p.kind as EpisodeKind,
        final: p.final as string | undefined,
        shorts: p.shorts as string[] | undefined,
        threshold: Number(p.threshold) || undefined,
      });
    } catch (e) {
      fail(e);
    }
  };

  const [advanced, setAdvanced] = useState(false);
  // 한 버튼: 처음이면 전체, 이미 처리했으면 캐시 재사용(순위만 / 포인트만)
  // 영상 읽기·전사·신호가 모두 끝난 회차만 캐시를 재사용한다 (prep 만 끝난 회차는 처음부터)
  const analyzed = isAnalyzed(selected);
  const quickStages = quickRunStages(selected, kind);
  const quickLabel = kind === "edited" ? "쇼츠 초안 만들기" : "편집 포인트 뽑기";
  const quickDesc = !analyzed
    ? kind === "edited"
      ? "영상을 읽고, 말을 글로 바꾸고, 득템·채팅·소리가 겹치는 순간을 찾아 세로 초안까지 만들어요. 4K 10분이면 약 10분 걸려요."
      : "영상을 읽고 신호를 찾아 편집할 구간 후보를 뽑아요. 원본 길이의 약 1/8 시간이 걸려요."
    : kind === "edited"
      ? "이미 읽어 둔 결과로 초안만 다시 만들어요. 1~2분이면 돼요."
      : "이미 읽어 둔 신호로 편집 포인트만 다시 뽑아요. 몇 초면 돼요.";
  const quickStart = async () => {
    if (!selected) return;
    try {
      await runJob(selected.id, quickStages, { layout, k, force: false, kind, threshold });
    } catch (e) {
      fail(e);
    }
  };
  // 자막만: 영상 읽기·전사가 안 됐으면 그것부터, 됐으면 자막 단계만
  const subtitleStages = subtitleRunStages(selected);
  const subtitlesDesc = selected?.stages?.transcribe
    ? "이미 글로 바꿔 둔 말로 자막 파일만 써요. 몇 초면 돼요."
    : "말을 글로 바꿔 자막 파일을 만들어요. 4K 10분이면 1~2분 걸려요.";
  const subtitlesOnly = async () => {
    if (!selected) return;
    try {
      await runJob(selected.id, subtitleStages, { layout, k, force: false, kind, threshold });
    } catch (e) {
      fail(e);
    }
  };
  // 자막 단계가 끝나면 토스트에 '자막 파일 열기' 액션
  const subsDoneAt = useRef(0);
  useEffect(() => {
    if (!lastDone || !lastDone.episode || lastDone.at === subsDoneAt.current || !lastDone.stages.includes("subtitles"))
      return;
    subsDoneAt.current = lastDone.at;
    api
      .episodePaths(lastDone.episode)
      .then((p) => {
        if (!p.subtitles_srt?.exists) return;
        const path = p.subtitles_srt.path;
        toast(`자막 파일이 생겼어요 — ${lastDone.episode}.srt`, false, {
          label: "자막 파일 열기",
          onClick: () => {
            if (shell) shell.shell.openPath(path).catch(fail);
            else {
              navigator.clipboard?.writeText(path).catch(() => {});
              toast(`경로를 복사했어요: ${path}`);
            }
          },
        });
      })
      .catch(() => {});
  }, [lastDone, toast, fail]);
  const state = activeJob?.status === "error" ? "error" : activeJob?.status === "done" ? "done" : "";
  const elapsed = activeJob?.started ? (activeJob.finished || Date.now() / 1000) - activeJob.started : 0;

  const runbar = (
    <div className="runbar" style={{ marginTop: simple ? 0 : 14 }}>
      <div>
        {running && activeJob.status === "running" && (
          <div className="bigpct">
            {Math.round(activeJob.pct)}%
            <small>
              {STAGE_LABEL[activeJob.stage as StageName] || activeJob.stage}
              {activeJob.eta_s != null && activeJob.eta_s > 0 ? ` · 약 ${fmtDur(activeJob.eta_s)} 남았어요` : ""}
            </small>
          </div>
        )}
        <Progress pct={activeJob?.pct ?? 0} state={state} indeterminate={activeJob?.status === "queued"} />
        <div className="status" style={{ marginTop: 6 }}>
          {running && <Spinner />}
          {activeJob ? (
            <>
              <b>{STATUS_KO[activeJob.status] || activeJob.status}</b>
              <span>
                {activeJob.stage && activeJob.status === "running"
                  ? `${STAGE_LABEL[activeJob.stage as StageName] || activeJob.stage} ${Math.round(activeJob.pct)}% · `
                  : ""}
                {activeJob.message}
              </span>
              {elapsed > 0 && <span className="muted">· {fmtDur(elapsed)}</span>}
              {!running && activeJob.status === "done" && <span className="ok">· 끝났어요</span>}
              {!running && activeJob.status === "queued" && activeJob.eta_s != null && (
                <span className="muted">· 예상 {fmtDur(activeJob.eta_s)}</span>
              )}
            </>
          ) : (
            <span className="muted">
              {simple ? "아직 만든 적이 없어요. 위 버튼 하나면 돼요." : "아직 실행한 적이 없어요. 위 버튼 하나면 돼요."}
            </span>
          )}
          {simple && running && (
            <>
              <span className="grow" style={{ flex: 1 }} />
              <Button variant="danger" size="sm" onClick={() => cancelJob().catch(fail)}>
                취소
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );

  const shortsCount = paths?.shorts_count ?? 0;
  const srt = paths?.subtitles_srt?.exists ? paths.subtitles_srt : null;

  return (
    <>
      {simple ? (
        <>
          <Card title="쇼츠 초안" right={selected && <span className="muted xs">{selected.id}</span>}>
            <div className="quick">
              <div className="grow">
                <div className="quick-title">{shortsCount ? `초안 ${shortsCount}개가 있어요` : "버튼 하나면 돼요"}</div>
                <div className="muted small">{quickDesc}</div>
              </div>
              <Button
                variant="primary"
                className="cta"
                onClick={quickStart}
                disabled={!selected || running}
                data-tip={TIP.quickRun}
              >
                {shortsCount ? "초안 다시 만들기" : quickLabel}
              </Button>
            </div>
            {shortsCount > 0 && paths && (
              <div className="row">
                <Button
                  size="sm"
                  onClick={() => {
                    location.hash = "#candidates";
                  }}
                >
                  초안 보러 가기
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => openPath(paths.shorts_dir.path)}
                  title={paths.shorts_dir.path}
                >
                  초안 폴더 열기
                </Button>
                {paths.premiere_shorts.exists && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => openPath(paths.premiere_shorts.path)}
                    title={paths.premiere_shorts.path}
                  >
                    Premiere 파일 열기
                  </Button>
                )}
              </div>
            )}
          </Card>
          <Card title="자막">
            <div className="quick">
              <div className="grow">
                <div className="quick-title">{srt ? "자막 파일이 준비됐어요" : "영상 전체 자막 파일"}</div>
                <div className="muted small">
                  {subtitlesDesc} Premiere 는 SRT 를, VEGAS Pro 는 .vegas.txt 를 가져가면 돼요.
                </div>
              </div>
              <Button
                variant="primary"
                className="cta"
                onClick={subtitlesOnly}
                disabled={!selected || running}
                data-tip={TIP.subtitlesOnly}
              >
                {srt ? "자막 다시 만들기" : "자막 만들기"}
              </Button>
            </div>
            {srt && paths && (
              <div className="row">
                <Button size="sm" onClick={() => openPath(srt.path)} title={srt.path}>
                  자막 파일 열기 (SRT)
                </Button>
                {paths.subtitles_vegas?.exists && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => openPath(paths.subtitles_vegas.path)}
                    data-tip={TIP.subtitlesVegas}
                  >
                    베가스용 열기
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => openPath(paths.subtitles_dir.path)}
                  title={paths.subtitles_dir.path}
                >
                  폴더 열기
                </Button>
              </div>
            )}
          </Card>
          <Card title="진행 상황">{runbar}</Card>
        </>
      ) : (
        <Card
          title={kind === "edited" ? "쇼츠 초안 만들기" : "편집 포인트 뽑기"}
          right={
            selected && (
              <span className="muted xs">
                {selected.id} · {KIND_LABEL[kind]}
              </span>
            )
          }
        >
          <div className="quick">
            <div className="grow">
              <div className="quick-title">{!analyzed ? "버튼 하나면 돼요" : "다시 만들 준비가 됐어요"}</div>
              <div className="muted small">{quickDesc}</div>
            </div>
            {running ? (
              <Button variant="danger" className="cta" onClick={() => cancelJob().catch(fail)}>
                취소
              </Button>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "stretch", gap: 8 }}>
                <Button
                  variant="primary"
                  className="cta"
                  onClick={quickStart}
                  disabled={!selected}
                  data-tip={TIP.quickRun}
                >
                  {quickLabel}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={subtitlesOnly}
                  disabled={!selected}
                  data-tip={TIP.subtitlesOnly}
                >
                  자막만 만들기
                </Button>
              </div>
            )}
          </div>
          <button className="adv-toggle" onClick={() => setAdvanced((v) => !v)}>
            {advanced ? "고급 설정 닫기 ▴" : "직접 단계를 고르거나 처음부터 다시 돌리기 ▾"}
          </button>
          <div hidden={!advanced}>
            <div className="stage-grid">
              {visible.map((s) => (
                <label key={s} className={cx("stage-opt", stages.has(s) && "on")} data-tip={STAGE_TIP[s]}>
                  <input type="checkbox" checked={stages.has(s)} onChange={() => toggle(s)} disabled={running} />
                  <span>
                    <span className="name">{STAGE_LABEL[s]}</span>
                    <br />
                    <span className="ko">{STAGE_TECH[s]}</span>
                  </span>
                  {selected?.stages?.[s] && (
                    <span className="done">
                      <Badge tone="ok">완료</Badge>
                    </span>
                  )}
                </label>
              ))}
            </div>
            {needsShorts && (
              <div className="shorts-pick">
                <div className="row">
                  <span className="small">
                    친구 쇼츠 파일 — 이 회차에서 잘라 올린 쇼츠를 주면 어느 구간인지 찾아 정답(keep)으로 기록해요
                  </span>
                  <span className="grow" style={{ flex: 1 }} />
                  {inShell ? (
                    <Button size="sm" onClick={pickShorts} disabled={running}>
                      쇼츠 추가…
                    </Button>
                  ) : (
                    <input
                      className="field sm"
                      style={{ minWidth: 260 }}
                      placeholder="경로 입력 후 Enter (폴더도 됨)"
                      disabled={running}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          const v = (e.target as HTMLInputElement).value.trim();
                          if (v) {
                            setShortsPaths((cur) => [...new Set([...cur, v])]);
                            (e.target as HTMLInputElement).value = "";
                          }
                        }
                      }}
                    />
                  )}
                </div>
                {shortsPaths.length > 0 && (
                  <ul className="shorts-list">
                    {shortsPaths.map((sp) => (
                      <li key={sp}>
                        <span className="mono xs">{sp}</span>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setShortsPaths((cur) => cur.filter((x) => x !== sp))}
                          disabled={running}
                        >
                          ✕
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {needsFinal && (
              <div className="row" style={{ marginTop: 12 }}>
                <span className="small">최종본(편집본) 파일</span>
                <input
                  className="field"
                  style={{ flex: 1, minWidth: 240 }}
                  placeholder="친구 편집본 mp4 경로 — 원본의 어느 구간이 살아남았는지 정답을 만들어요"
                  value={finalPath}
                  onChange={(e) => setFinalPath(e.target.value)}
                  disabled={running}
                />
                {inShell && (
                  <Button size="sm" onClick={pickFinal} disabled={running}>
                    찾기…
                  </Button>
                )}
              </div>
            )}
            <div className="row" style={{ marginTop: 12 }}>
              {PRESETS.filter((p) => p.kinds.includes(kind)).map((p) => (
                <Button
                  key={p.key}
                  variant="ghost"
                  size="sm"
                  title={p.title}
                  onClick={() => setStages(new Set(p.stages.length ? p.stages : DEFAULT_STAGES[kind]))}
                  disabled={running}
                >
                  {p.label}
                </Button>
              ))}
              <span className="sep" />
              {kind === "edited" ? (
                <>
                  <label className="check" data-tip={TIP.layout}>
                    레이아웃
                    <select
                      className="field sm"
                      value={layout}
                      onChange={(e) => setLayout(e.target.value as Layout)}
                      disabled={running}
                      title="card = 친구 확정 포맷(제목 띠 + 템 창 크롭 + 채팅). feed 는 실험용"
                    >
                      <option value="card">card (확정)</option>
                      <option value="feed">feed (실험)</option>
                    </select>
                  </label>
                  <label className="check" data-tip={TIP.topk}>
                    초안 개수{" "}
                    <input
                      className="field sm num"
                      type="number"
                      min={1}
                      max={10}
                      value={k}
                      onChange={(e) => setK(Number(e.target.value) || 5)}
                      disabled={running}
                    />
                  </label>
                </>
              ) : (
                <label className="check" data-tip={TIP.threshold}>
                  민감도(낮을수록 많이){" "}
                  <input
                    className="field sm num"
                    type="number"
                    step={0.1}
                    min={0.2}
                    max={5}
                    value={threshold}
                    onChange={(e) => setThreshold(Number(e.target.value) || 1.5)}
                    disabled={running}
                  />
                </label>
              )}
              <label className={cx("check", force && "on")} data-tip={TIP.force}>
                <input
                  type="checkbox"
                  checked={force}
                  onChange={(e) => setForce(e.target.checked)}
                  disabled={running}
                />{" "}
                처음부터 다시
              </label>
              <span className="grow" style={{ flex: 1 }} />
              {running ? (
                <Button variant="danger" onClick={() => cancelJob().catch(fail)}>
                  취소
                </Button>
              ) : (
                <Button variant="primary" onClick={start} disabled={!selected || !ordered.length}>
                  선택한 단계 실행 {ordered.length ? `(${ordered.length})` : ""}
                </Button>
              )}
            </div>
          </div>
          {kind === "original" && (
            <p className="muted xs" style={{ marginTop: 8 }}>
              원본은 길어서 OCR 이 무거운 신호(채팅 텍스트)와 편집본 전용 신호(컷 밀도·줌 강조)는 돌리지 않아요. 득템
              배너는 화면이 바뀔 때만 읽어요.
            </p>
          )}
          {runbar}
        </Card>
      )}

      {activeJob?.status === "done" && (activeJob.warnings?.length ?? 0) > 0 && (
        <div className="warnbox" role="status">
          {activeJob.warnings!.map((w) => (
            <div key={w.code}>
              <b>{w.message}</b>
              <div className="hint">{w.hint}</div>
            </div>
          ))}
        </div>
      )}

      {runError && (
        <div className="errbox" role="alert">
          <div className="head">
            <span className="code">{runError.info.code}</span>
            <span className="msg">{runError.info.message}</span>
          </div>
          <div className="hint">
            {runError.info.hint || (runError.info.kind === "internal" ? "내부 오류예요. 로그를 확인하세요." : "")}
          </div>
          <div className="btns">
            {runError.job && (
              <Button variant="primary" size="sm" onClick={retry}>
                같은 설정으로 다시 실행
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={dismissError}>
              닫기
            </Button>
          </div>
        </div>
      )}

      {!simple && <LogPane />}
    </>
  );
}

export function LogPane() {
  const { log, logTitle, logPath, clearLog } = useApp();
  const [errOnly, setErrOnly] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = box.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [log]);
  return (
    <div className="logpane" style={{ marginTop: 12 }}>
      <div className="logbar">
        <span className="grow" title={logPath}>
          {logTitle === "로그" ? "진행 기록" : logTitle}
          {logPath ? ` — ${logPath}` : ""}
        </span>
        <label className="check xs">
          <input type="checkbox" checked={errOnly} onChange={(e) => setErrOnly(e.target.checked)} /> 오류만
        </label>
        <Button variant="ghost" size="sm" onClick={clearLog}>
          지우기
        </Button>
      </div>
      <div ref={box} className={cx("log", errOnly && "err-only")}>
        {log.length ? (
          log.map((l, i) => (
            <div key={i} className={cx("line", l.level)}>
              {l.stage && <span className="st">{l.stage}</span>}
              {l.message}
            </div>
          ))
        ) : (
          <div className="nothing">실행하면 진행 기록이 여기 쌓여요. 기록 탭에서 이전 작업을 눌러도 볼 수 있어요.</div>
        )}
      </div>
    </div>
  );
}
