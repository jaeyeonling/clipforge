import { useState } from "react";
import { STAGES } from "../api/types";
import { Button, cx, fmtTime } from "../components/ui";
import { useApp } from "../state/store";

export function Sidebar() {
  const { episodes, selected, selectEpisode, addEpisode, fail, refreshEpisodes } = useApp();
  const [path, setPath] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!path.trim()) return;
    setBusy(true);
    try { await addEpisode(path.trim(), title.trim()); setPath(""); setTitle(""); } catch (e) { fail(e); } finally { setBusy(false); }
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <h2>회차 {episodes.length ? `· ${episodes.length}` : ""}</h2>
        <Button variant="ghost" size="sm" onClick={() => refreshEpisodes().catch(fail)} title="목록 새로고침">↻</Button>
      </div>
      <ul className="episodes">
        {episodes.map((e) => {
          const done = STAGES.filter((s) => e.stages?.[s]).length;
          return (
            <li key={e.id} className={cx("ep", selected?.id === e.id && "active")} onClick={() => selectEpisode(e.id)}>
              <div className="id">{e.id}</div>
              {e.title && <div className="title" title={e.title}>{e.title}</div>}
              <div className="meta">{e.duration ? `${fmtTime(e.duration)} · ${e.width}×${e.height} · ${e.game || ""}` : "아직 처리 전"}{done ? ` · ${done}/${STAGES.length} 단계` : ""}</div>
              <div className="stage-dots" title={STAGES.map((s) => `${s}: ${e.stages?.[s] ? "완료" : "-"}`).join("\n")}>
                {STAGES.map((s) => <i key={s} className={cx(e.stages?.[s] && "on")} />)}
              </div>
            </li>
          );
        })}
        {!episodes.length && <li className="muted small" style={{ padding: 12 }}>videos/ 폴더에 mp4 를 넣거나 아래에서 등록하세요.</li>}
      </ul>
      <form className="add-form" onSubmit={(ev) => { ev.preventDefault(); submit(); }}>
        <input className="field" placeholder="영상 파일 경로 (C:\...\ep60.mp4)" value={path} onChange={(e) => setPath(e.target.value)} />
        <input className="field" placeholder="유튜브 제목 (약한 정답용, 선택)" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Button type="submit" disabled={busy || !path.trim()}>{busy ? "등록 중…" : "회차 등록"}</Button>
      </form>
    </aside>
  );
}
