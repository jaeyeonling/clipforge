import { STAGE_LABEL, type StageName } from "../api/types";
import { useApp } from "../state/store";
import { cx } from "../components/ui";
import { TIP } from "../api/tips";

export function Header() {
  const { health: h, wsConnected, activeJob } = useApp();
  const chip = (label: string, ok: boolean | undefined, extra?: string, warnOnly?: boolean, tip?: string) => (
    <span className={cx("chip", ok ? "ok" : warnOnly ? "warn" : "bad")} data-tip={`${tip || ""}${extra ? `\n(${extra})` : ""}\n상태: ${ok ? "정상" : warnOnly ? "없음 (느리게 동작)" : "없음 (필요)"}`}><span className="dot" />{label}{extra ? ` ${extra}` : ""}</span>
  );
  return (
    <header className="header">
      <div className="brand">clipforge <span className="ver">{h ? `v${h.engine_version}` : ""}</span></div>
      {activeJob && (activeJob.status === "running" || activeJob.status === "queued") && (
        <span className="pill live">{activeJob.episode} · {STAGE_LABEL[activeJob.stage as StageName] || activeJob.stage || "대기"} {Math.round(activeJob.pct)}%</span>
      )}
      <span className="grow" />
      {h && (
        <div className="chips">
          {chip("영상 도구", h.ffmpeg_ok, undefined, false, TIP.chipFfmpeg)}
          {chip("GPU 인코딩", h.nvenc, undefined, true, TIP.chipNvenc)}
          {chip("GPU", !!h.gpu, h.gpu ? h.gpu.split(",")[0].replace("NVIDIA GeForce ", "") : "없음", true, TIP.chipGpu)}
          {chip("음성 인식 GPU", h.whisper_gpu, undefined, true, TIP.chipWhisper)}
          {chip("글자 인식", h.rapidocr, undefined, false, TIP.chipOcr)}
          {chip("폰트", h.fonts_ok, undefined, false, TIP.chipFonts)}
          {h.disk_free_gb != null && chip("디스크", h.disk_free_gb >= 10, `${h.disk_free_gb}GB`, true, TIP.chipDisk)}
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
