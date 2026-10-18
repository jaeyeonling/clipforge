import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { CalibResult, Profile } from "../api/types";
import { Badge, Button, Card, Empty, Spinner } from "../components/ui";
import { useApp } from "../state/store";

export function Calibration() {
  const { selected, toast, fail } = useApp();
  const [result, setResult] = useState<CalibResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [t, setT] = useState(200);
  const [img, setImg] = useState<string | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [rois, setRois] = useState<Record<string, number[]> | null>(null);
  const game = result?.game || selected?.game || "d2r";

  useEffect(() => { setResult(null); setImg(null); setRois(null); }, [selected?.id]);

  const preview = useCallback(async (override?: Record<string, number[]> | null) => {
    if (!selected) return;
    try { const r = await api.calibratePreview(selected.id, t, override ?? null); setImg(`${r.url}${r.url.includes("?") ? "&" : "?"}_=${Date.now()}`); } catch (e) { fail(e); }
  }, [selected, t, fail]);

  const check = async () => {
    if (!selected) return;
    setChecking(true);
    try { const r = await api.calibrate(selected.id); setResult(r); if (r.ok) await preview(); } catch (e) { fail(e); } finally { setChecking(false); }
  };
  const openEditor = async () => {
    try { const p = await api.profile(game); setProfile(p); setRois(Object.fromEntries(Object.entries(p.rois).map(([k, v]) => [k, [...v]]))); } catch (e) { fail(e); }
  };
  const save = async () => {
    if (!rois) return;
    try { const r = await api.saveProfile(game, rois); toast(r.note || "저장됨"); } catch (e) { fail(e); }
  };
  const setVal = (k: string, i: number, v: number) => setRois((cur) => cur && { ...cur, [k]: cur[k].map((x, j) => (j === i ? v : x)) });

  if (!selected) return <Empty title="회차를 선택하세요" />;

  return (
    <div className="calib">
      <div>
        <Card title="ROI 점검" right={<Button size="sm" variant="primary" onClick={check} disabled={checking}>{checking ? "점검 중…" : "점검"}</Button>}>
          {!result && <p className="muted small">득템 배너·패널 제목·채팅·HUD 영역이 이 회차 화면과 맞는지 캐시된 OCR 결과로 적중률을 계산합니다. prep 과 signals 가 끝난 뒤에 눌러 주세요.</p>}
          {result && !result.ok && <p className="muted small">{result.error}</p>}
          {result?.ok && (
            <>
              <div className="row" style={{ marginBottom: 10 }}><span className="small">{result.game} · {result.resolution.join("×")}</span><Badge tone={result.status}>{result.status}</Badge></div>
              <ul className="checks">
                {result.checks.map((c) => (
                  <li key={c.name}>
                    <Badge tone={c.status}>{c.status}</Badge>
                    <div><b>{c.name}</b>{c.rate != null && <span className="rate">{Math.round(c.rate * 100)}%</span>}<div className="detail">{c.detail}</div>{c.hint && <div className="hint">{c.hint}</div>}</div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
        <Card title="ROI 편집 (비율 0~1)" right={rois ? <Button size="sm" variant="ghost" onClick={() => setRois(null)}>닫기</Button> : <Button size="sm" onClick={openEditor}>열기</Button>}>
          {!rois && <p className="muted small">게임 프로필 {game} 의 ROI 수치를 고쳐 미리보기로 확인한 뒤 저장합니다.</p>}
          {rois && (
            <>
              <table className="roi-table">
                <thead><tr><th>ROI</th><th>x</th><th>y</th><th>w</th><th>h</th></tr></thead>
                <tbody>
                  {Object.entries(rois).map(([k, v]) => (
                    <tr key={k}><td className="name">{k}</td>{v.map((x, i) => <td key={i}><input className="field sm" type="number" step={0.005} min={0} max={1} value={x} onChange={(e) => setVal(k, i, Number(e.target.value))} /></td>)}</tr>
                  ))}
                </tbody>
              </table>
              <div className="row" style={{ marginTop: 10 }}>
                <Button size="sm" onClick={() => preview(rois)}>미리보기 갱신</Button>
                <Button size="sm" variant="primary" onClick={save}>프로필 저장</Button>
                {profile?.name && <span className="muted xs">games/{profile.name}.yaml</span>}
              </div>
              <p className="muted xs" style={{ marginTop: 8 }}>네이티브 크롭(배너·채팅)이 바뀌는 ROI 는 다음 prep(강제 재계산)부터 반영됩니다.</p>
            </>
          )}
        </Card>
      </div>
      <Card title="미리보기" right={
        <span className="row">
          <label className="check xs">프레임(초) <input className="field sm num" type="number" min={0} value={t} onChange={(e) => setT(Number(e.target.value) || 0)} /></label>
          <Button size="sm" onClick={() => preview(rois)}>보기</Button>
        </span>}>
        <div className="preview">
          {img ? <img src={img} alt="ROI 미리보기" /> : <div className="empty" style={{ aspectRatio: "16/9" }}>{checking ? <Spinner /> : <span className="small">점검 또는 보기를 누르면 ROI 박스를 그린 프레임이 나옵니다.</span>}</div>}
        </div>
      </Card>
    </div>
  );
}
