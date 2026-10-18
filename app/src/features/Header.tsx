import { STAGE_LABEL, type StageName } from "../api/types";
import { useApp } from "../state/store";
import { cx } from "../components/ui";
import { TIP } from "../api/tips";

export function Header() {
  const { health: h, wsConnected, activeJob } = useApp();
  // 환경 상태를 칩 하나로: 필수가 빠지면 빨강, 선택이 빠지면 노랑(느리게 동작), 다 있으면 초록. 자세한 건 설정 탭.
  const items = h ? [
    { label: "영상 도구", ok: h.ffmpeg_ok, need: true, tip: TIP.chipFfmpeg },
    { label: "글자 인식", ok: h.rapidocr, need: true, tip: TIP.chipOcr },
    { label: "폰트", ok: h.fonts_ok, need: true, tip: TIP.chipFonts },
    { label: "GPU 인코딩", ok: h.nvenc, need: false, tip: TIP.chipNvenc },
    { label: "음성 인식 GPU", ok: h.whisper_gpu, need: false, tip: TIP.chipWhisper },
    { label: "디스크 여유", ok: h.disk_free_gb == null || h.disk_free_gb >= 10, need: false, tip: TIP.chipDisk },
  ] : [];
  const bad = items.filter((i) => !i.ok && i.need), warn = items.filter((i) => !i.ok && !i.need);
  const tone = bad.length ? "bad" : warn.length ? "warn" : "ok";
  const label = bad.length ? `${bad.map((i) => i.label).join(" · ")} 없음` : warn.length ? "느리게 동작" : "준비 완료";
  const tip = bad.length ? `${bad.map((i) => `${i.label}: ${i.tip}`).join("\n")}\n\n설정 탭에서 자세히 볼 수 있어요.`
    : warn.length ? `${warn.map((i) => `${i.label} 없음 — ${i.tip}`).join("\n")}\n\n없어도 되지만 느려요. 설정 탭에서 자세히.`
    : `영상 도구 · 글자 인식 · 폰트 · GPU 모두 준비됐어요.${h?.gpu ? `\n${h.gpu.split(",")[0]}` : ""}`;
  return (
    <header className="header">
      <div className="brand">clipforge <span className="ver">{h ? `v${h.engine_version}` : ""}</span></div>
      {activeJob && (activeJob.status === "running" || activeJob.status === "queued") && (
        <span className="pill live">{activeJob.episode} · {STAGE_LABEL[activeJob.stage as StageName] || activeJob.stage || "대기"} {Math.round(activeJob.pct)}%</span>
      )}
      <span className="grow" />
      {h && <button className={cx("status-chip", tone)} data-tip={tip} onClick={() => { location.hash = "#settings"; }}><span className="dot" />{label}</button>}
      {!wsConnected && <span className="pill bad" title="엔진과의 실시간 연결이 끊겼어요. 자동으로 다시 연결해요.">연결 끊김</span>}
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
