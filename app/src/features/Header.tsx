import { useApp } from "../state/store";
import { cx } from "../components/ui";

export function Header() {
  const { health: h, wsConnected, activeJob } = useApp();
  const chip = (label: string, ok: boolean | undefined, extra?: string, warnOnly?: boolean) => (
    <span className={cx("chip", ok ? "ok" : warnOnly ? "warn" : "bad")} title={extra}><span className="dot" />{label}{extra ? ` ${extra}` : ""}</span>
  );
  return (
    <header className="header">
      <div className="brand">clipforge <span className="ver">{h ? `v${h.engine_version}` : ""}</span></div>
      {activeJob && (activeJob.status === "running" || activeJob.status === "queued") && (
        <span className="pill live">{activeJob.episode} · {activeJob.stage || "대기"} {Math.round(activeJob.pct)}%</span>
      )}
      <span className="grow" />
      {h && (
        <div className="chips" title={`app: ${h.app_root}\ndata: ${h.data_root}\nffmpeg: ${h.ffmpeg || "-"}\nlog: ${h.log_path}`}>
          {chip("ffmpeg", h.ffmpeg_ok)}
          {chip("NVENC", h.nvenc, undefined, true)}
          {chip("GPU", !!h.gpu, h.gpu ? h.gpu.split(",")[0] : "없음", true)}
          {chip("Whisper GPU", h.whisper_gpu, undefined, true)}
          {chip("OCR", h.rapidocr)}
          {chip("폰트", h.fonts_ok)}
          {h.disk_free_gb != null && chip("디스크", h.disk_free_gb >= 10, `${h.disk_free_gb}GB`, true)}
        </div>
      )}
      {!wsConnected && <span className="pill bad" title="엔진과의 실시간 연결이 끊겼습니다. 자동으로 다시 연결합니다.">연결 끊김</span>}
    </header>
  );
}

export function Alerts() {
  const { health } = useApp();
  const probs = health?.problems ?? [];
  return (
    <div className="alerts">
      {probs.map((p) => (
        <div key={p.code} className={cx("alert", p.level)}>
          <span className="lv">{p.level === "error" ? "오류" : "주의"}</span>
          <div><b>{p.message}</b><span className="code">{p.code}</span><div className="hint">{p.hint}</div></div>
        </div>
      ))}
    </div>
  );
}
