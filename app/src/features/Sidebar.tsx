import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { api } from "../api/client";
import { DEFAULT_STAGES, KIND_LABEL, type EpisodeKind, type GameInfo } from "../api/types";
import { Button, cx, fmtTime } from "../components/ui";
import { inShell, shell } from "../shell";
import { useApp } from "../state/store";
import { TIP } from "../api/tips";

const VIDEO_RE = /\.(mp4|mkv|mov|m4v|ts|flv|webm)$/i;

export function Sidebar() {
  const { episodes, selected, selectEpisode, refreshEpisodes, registerVideos, toast, fail, simple } = useApp();
  const [path, setPath] = useState("");
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<EpisodeKind>("edited");
  const [games, setGames] = useState<GameInfo[]>([]);
  const [game, setGame] = useState("d2r");
  useEffect(() => {
    api
      .games()
      .then((g) => {
        setGames(g);
        if (g.length && !g.some((x) => x.key === game)) setGame(g[0].key);
      })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const [busy, setBusy] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const dragDepth = useRef(0);

  /** 여러 파일 등록. 제목은 파일이 하나일 때만 적용. 복사하지 않는다(같은 드라이브면 하드링크, 아니면 원본 경로 참조). */
  const register = useCallback(
    async (paths: string[], titleForSingle = "") => {
      if (!paths.some((p) => VIDEO_RE.test(p))) {
        toast("영상 파일(mp4/mkv/mov)이 아니에요", true);
        return;
      }
      try {
        await registerVideos(paths, { title: titleForSingle, kind, game }, setBusy);
      } finally {
        setBusy(null);
      }
    },
    [toast, registerVideos, kind, game],
  );

  const submit = async () => {
    if (path.trim()) {
      await register([path.trim()], title.trim());
      setPath("");
      setTitle("");
    }
  };
  const pick = async () => {
    if (!shell) return;
    try {
      const ps = await shell.shell.pickVideos();
      if (ps.length) await register(ps, title.trim());
    } catch (e) {
      fail(e);
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    dragDepth.current = 0;
    setDrag(false);
    const files = Array.from(e.dataTransfer.files);
    if (!files.length) return;
    if (!shell) {
      toast("브라우저에서는 파일 경로를 알 수 없어요. 경로를 입력하거나 데스크톱 앱을 쓰세요.", true);
      return;
    }
    const sh = shell;
    register(
      files.map((f) => sh.shell.pathForFile(f)),
      title.trim(),
    );
  };
  const onDragEnter = (e: DragEvent) => {
    e.preventDefault();
    dragDepth.current++;
    setDrag(true);
  };
  const onDragLeave = () => {
    dragDepth.current--;
    if (dragDepth.current <= 0) {
      dragDepth.current = 0;
      setDrag(false);
    }
  };

  return (
    <aside
      className={cx("sidebar", drag && "drag")}
      onDragEnter={onDragEnter}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <div className="sidebar-head">
        <h2>
          {simple ? "영상" : "회차"} {episodes.length ? `· ${episodes.length}` : ""}
        </h2>
        <Button variant="ghost" size="sm" onClick={() => refreshEpisodes().catch(fail)} title="목록 새로고침">
          ↻
        </Button>
      </div>
      <ul className="episodes">
        {episodes.map((e) => {
          const want = DEFAULT_STAGES[e.kind || "edited"];
          const done = want.filter((s) => e.stages?.[s]).length;
          return (
            <li key={e.id} className={cx("ep", selected?.id === e.id && "active")} onClick={() => selectEpisode(e.id)}>
              <div className="id">
                {e.id}
                {e.kind === "original" && (
                  <span className="badge xs accent" title="원본 녹화 → 편집 포인트 (Phase 2)">
                    원본
                  </span>
                )}
                {e.linked === false && (
                  <span className="badge xs" title={`원본 경로 참조: ${e.source}`}>
                    참조
                  </span>
                )}
              </div>
              {e.title && (
                <div className="title" title={e.title}>
                  {e.title}
                </div>
              )}
              <div className="meta">
                {e.duration ? `${fmtTime(e.duration)} · ${e.width}×${e.height}` : "아직 분석 전"}
                {simple
                  ? (e.stages?.export ? " · 초안 있음" : "") + (e.stages?.subtitles ? " · 자막 있음" : "")
                  : done
                    ? ` · ${done}/${want.length} 단계 완료`
                    : ""}
              </div>
              {!simple && (
                <div className="stage-dots" title={want.map((s) => `${s}: ${e.stages?.[s] ? "완료" : "-"}`).join("\n")}>
                  {want.map((s) => (
                    <i key={s} className={cx(e.stages?.[s] && "on")} />
                  ))}
                </div>
              )}
            </li>
          );
        })}
        {!episodes.length && (
          <li className="muted small" style={{ padding: 12 }}>
            아직 넣은 영상이 없어요. 아래 버튼을 누르거나 여기에 끌어다 놓으세요.
          </li>
        )}
      </ul>
      <form
        className="add-form"
        onSubmit={(ev) => {
          ev.preventDefault();
          submit();
        }}
      >
        {drag && <div className="dropzone">영상을 놓으면 등록돼요</div>}
        {!simple && games.length > 1 && (
          <select
            className="field"
            value={game}
            onChange={(e) => setGame(e.target.value)}
            disabled={!!busy}
            title="게임 프로필 (화면 영역·사전)"
          >
            {games.map((g) => (
              <option key={g.key} value={g.key}>
                {g.name}
              </option>
            ))}
          </select>
        )}
        {!simple && (
          <select
            className="field"
            value={kind}
            onChange={(e) => setKind(e.target.value as EpisodeKind)}
            disabled={!!busy}
            data-tip={TIP.kindSelect}
          >
            {(Object.keys(KIND_LABEL) as EpisodeKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </select>
        )}
        {!simple && (
          <input
            className="field"
            placeholder="유튜브 제목 (선택)"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={!!busy}
            data-tip={TIP.titleInput}
          />
        )}
        {inShell ? (
          <Button type="button" variant="primary" onClick={pick} disabled={!!busy}>
            {busy || "영상 넣기"}
          </Button>
        ) : (
          <>
            <input
              className="field"
              placeholder="영상 파일 경로 (C:\...\ep60.mp4)"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              disabled={!!busy}
            />
            <Button type="submit" disabled={!!busy || !path.trim()}>
              {busy || "회차 등록"}
            </Button>
          </>
        )}
        <div className="muted xs">영상을 복사하지 않아요. 창에 끌어다 놓아도 돼요.</div>
      </form>
    </aside>
  );
}
