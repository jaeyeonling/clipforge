import { useCallback, useEffect, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { api } from "../api/client";
import type { CalibResult, PreviewResult } from "../api/types";
import { Badge, Button, Card, Empty, Spinner, cx } from "../components/ui";
import { useApp } from "../state/store";
import { TIP } from "../api/tips";

type Rois = Record<string, number[]>;
const ROI_LABEL: Record<string, string> = { banner: "득템 배너", chat: "채팅", zone: "지역명", hud_red_orb: "체력 구슬", hud_blue_orb: "마나 구슬" };
const STATUS_LABEL: Record<string, string> = { pass: "통과", warn: "주의", fail: "실패", skip: "건너뜀" };
const STATUS_TIP: Record<string, string> = { pass: TIP.roiPass, warn: TIP.roiWarn, fail: TIP.roiFail, skip: "점검할 자료가 아직 없어요 (분석을 먼저)." };
const ROI_TIP: Record<string, string> = { banner: "좌상단 '득템 :' 배너. 새 아이템이 적히는 순간이 쇼츠 1순위 근거예요.", chat: "채팅 오버레이. 채팅이 터지는 순간과 하이라이트 자막에 써요.", zone: "우상단 지역·난이도 글자.", hud_red_orb: "체력 구슬. 둘 다 안 보이면 게임 화면이 아닌 것(줌·카드)으로 봐요.", hud_blue_orb: "마나 구슬." };
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const r4 = (v: number) => Math.round(v * 10000) / 10000;

/**
 * 캘리브레이션: 점검(적중률) · 미리보기 · ROI 편집.
 * 편집은 원본 프레임 위에서 박스를 끌어 옮기고(본체) 모서리로 크기를 바꾼다(비율 좌표). 숫자 표와 양방향 동기. 저장은 games/<game>.yaml.
 */
export function Calibration() {
  const { selected, toast, fail } = useApp();
  const [result, setResult] = useState<CalibResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [t, setT] = useState(200);
  const [prev, setPrev] = useState<PreviewResult | null>(null);
  const [editing, setEditing] = useState(false);
  const [rois, setRois] = useState<Rois | null>(null);
  const [dirty, setDirty] = useState(false);
  const game = result?.game || selected?.game || "d2r";

  useEffect(() => { setResult(null); setPrev(null); setRois(null); setEditing(false); setDirty(false); }, [selected?.id]);

  const preview = useCallback(async (override?: Rois | null, at?: number) => {
    if (!selected) return null;
    try {
      const r = await api.calibratePreview(selected.id, at ?? t, override ?? null);
      setPrev({ ...r, url: `${r.url}${r.url.includes("?") ? "&" : "?"}_=${Date.now()}` });
      return r;
    } catch (e) { fail(e); return null; }
  }, [selected, t, fail]);

  const check = async () => {
    if (!selected) return;
    setChecking(true);
    try { const r = await api.calibrate(selected.id); setResult(r); if (r.ok) await preview(rois); } catch (e) { fail(e); } finally { setChecking(false); }
  };
  const openEditor = async () => {
    try {
      const p = await api.profile(game);
      const init: Rois = Object.fromEntries(Object.entries(p.rois).map(([k, v]) => [k, [...v]]));
      setRois(init); setDirty(false); setEditing(true);
      if (!prev) await preview(init);
    } catch (e) { fail(e); }
  };
  const save = async () => {
    if (!rois) return;
    try { const r = await api.saveProfile(game, Object.fromEntries(Object.entries(rois).map(([k, v]) => [k, v.map(r4)]))); toast(r.note || "저장됨"); setDirty(false); await preview(rois); } catch (e) { fail(e); }
  };
  const setVal = (k: string, i: number, v: number) => { setRois((cur) => cur && { ...cur, [k]: cur[k].map((x, j) => (j === i ? clamp(v, 0, 1) : x)) }); setDirty(true); };
  const setBox = (k: string, box: number[]) => { setRois((cur) => cur && { ...cur, [k]: box }); setDirty(true); };

  if (!selected) return <Empty title="회차를 선택하세요" />;

  return (
    <div className="calib">
      <div>
        <Card title="화면 영역 점검" right={<Button size="sm" variant="primary" onClick={check} disabled={checking} data-tip={TIP.roiCheck}>{checking ? "점검 중…" : "점검"}</Button>}>
          {!result && <p className="muted small">득템 배너·창 제목·채팅·체력/마나 구슬이 이 회차 화면의 어디에 있는지 프로그램이 제대로 보고 있는지 확인해요. 분석을 한 번 돌린 뒤에 눌러 주세요. 방송 화면 배치를 바꾼 회차라면 꼭 보세요.</p>}
          {result && !result.ok && <p className="muted small">{result.error}</p>}
          {result?.ok && (
            <>
              <div className="row" style={{ marginBottom: 10 }}><span className="small">{result.game} · {result.resolution.join("×")}</span><Badge tone={result.status}>{STATUS_LABEL[result.status] || result.status}</Badge></div>
              <ul className="checks">
                {result.checks.map((c) => (
                  <li key={c.name}>
                    <span data-tip={STATUS_TIP[c.status]}><Badge tone={c.status}>{STATUS_LABEL[c.status] || c.status}</Badge></span>
                    <div><b>{c.name}</b>{c.rate != null && <span className="rate">{Math.round(c.rate * 100)}%</span>}<div className="detail">{c.detail}</div>{c.hint && <div className="hint">{c.hint}</div>}</div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
        <Card title={<span data-tip={TIP.roiEdit}>영역 위치 고치기</span>} right={editing ? <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setRois(null); setDirty(false); }}>닫기</Button> : <Button size="sm" onClick={openEditor}>열기</Button>}>
          {!editing && <p className="muted small">열면 오른쪽 화면 위에서 박스를 끌어 옮기고 모서리로 크기를 바꿀 수 있어요. 저장하면 이 게임 설정({game})에 기록돼 다음 회차부터 적용돼요.</p>}
          {editing && rois && (
            <>
              <table className="roi-table">
                <thead><tr><th>영역</th><th>왼쪽</th><th>위</th><th>너비</th><th>높이</th></tr></thead>
                <tbody>
                  {Object.entries(rois).map(([k, v]) => (
                    <tr key={k}><td className="name" data-tip={ROI_TIP[k] || k} style={{ color: prev?.colors[k] }}>{ROI_LABEL[k] || k}</td>{v.map((x, i) => <td key={i}><input className="field sm" type="number" step={0.005} min={0} max={1} value={r4(x)} onChange={(e) => setVal(k, i, Number(e.target.value))} /></td>)}</tr>
                  ))}
                </tbody>
              </table>
              <div className="row" style={{ marginTop: 10 }}>
                <Button size="sm" variant="primary" onClick={save} disabled={!dirty}>프로필 저장{dirty ? " *" : ""}</Button>
                <Button size="sm" variant="ghost" onClick={openEditor}>되돌리기</Button>
              </div>
              <p className="muted xs" style={{ marginTop: 8 }}>수치는 화면 전체를 1로 본 비율이에요. 배너·채팅 영역을 바꿨으면 실행 탭 고급 설정에서 '처음부터 다시'로 한 번 돌려야 반영돼요. 점선(창 제목 띠)은 자동이에요.</p>
            </>
          )}
        </Card>
      </div>
      <Card title={editing ? "박스를 끌어 옮기고 모서리로 크기 조절" : "미리보기"} right={
        <span className="row">
          <label className="check xs">시각(초) <input className="field sm num" type="number" min={0} max={prev?.n_frames ? prev.n_frames - 1 : undefined} value={t} onChange={(e) => setT(Number(e.target.value) || 0)} /></label>
          <Button size="sm" variant="ghost" onClick={() => { const n = Math.max(0, t - 30); setT(n); preview(rois, n); }}>−30s</Button>
          <Button size="sm" variant="ghost" onClick={() => { const n = t + 30; setT(n); preview(rois, n); }}>+30s</Button>
          <Button size="sm" onClick={() => preview(rois)}>보기</Button>
        </span>}>
        <div className="preview">
          {!prev ? <div className="empty" style={{ aspectRatio: "16/9" }}>{checking ? <Spinner /> : <span className="small">점검 또는 보기를 누르면 영역 박스를 그린 화면이 나와요.</span>}</div>
            : editing && rois ? <RoiCanvas frameUrl={prev.frame_url} rois={rois} bands={prev.panel_bands} colors={prev.colors} onChange={setBox} />
            : <img src={prev.url} alt="ROI 미리보기" />}
          {prev && <div className="muted xs" style={{ marginTop: 6 }}>{prev.t}초 지점 (0~{prev.n_frames - 1}) · 원본 {prev.frame_size[0]}×{prev.frame_size[1]}</div>}
        </div>
      </Card>
    </div>
  );
}

/** 원본 프레임 + 비율 박스. 포인터 드래그로 이동/크기 변경. 좌표는 컨테이너 크기 대비 비율이라 창 크기와 무관. */
function RoiCanvas({ frameUrl, rois, bands, colors, onChange }: { frameUrl: string; rois: Rois; bands: Record<string, number[]>; colors: Record<string, string>; onChange: (k: string, box: number[]) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<{ k: string; mode: "move" | "resize"; sx: number; sy: number; start: number[] } | null>(null);

  const begin = (k: string, mode: "move" | "resize") => (e: RPointerEvent) => {
    e.preventDefault(); e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { k, mode, sx: e.clientX, sy: e.clientY, start: [...rois[k]] };
  };
  const move = (e: RPointerEvent) => {
    const d = drag.current, el = box.current; if (!d || !el) return;
    const W = el.clientWidth, H = el.clientHeight;
    const dx = (e.clientX - d.sx) / W, dy = (e.clientY - d.sy) / H;
    const [x, y, w, h] = d.start;
    if (d.mode === "move") onChange(d.k, [clamp(x + dx, 0, 1 - w), clamp(y + dy, 0, 1 - h), w, h]);
    else onChange(d.k, [x, y, clamp(w + dx, 0.005, 1 - x), clamp(h + dy, 0.005, 1 - y)]);
  };
  const end = () => { drag.current = null; };

  return (
    <div ref={box} className="roi-canvas" onPointerMove={move} onPointerUp={end} onPointerCancel={end}>
      <img src={frameUrl} alt="프레임" draggable={false} />
      {Object.entries(bands).map(([side, [x, y, w, h]]) => (
        <div key={side} className="roi-band" style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` }}><span>panel_{side}</span></div>
      ))}
      {Object.entries(rois).map(([k, [x, y, w, h]]) => (
        <div key={k} className={cx("roi-box")} style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%`, borderColor: colors[k] || "#fff" }} onPointerDown={begin(k, "move")}>
          <span className="tag" style={{ background: colors[k] || "#fff" }}>{k}</span>
          <i className="handle" style={{ background: colors[k] || "#fff" }} onPointerDown={begin(k, "resize")} />
        </div>
      ))}
    </div>
  );
}
