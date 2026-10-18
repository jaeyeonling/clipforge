import { useState } from "react";
import pkg from "../../package.json";
import { Badge, Button, Card, Empty, cx } from "../components/ui";
import { useApp } from "../state/store";
import { COMPONENT_LABEL, human, inShell, shell, useShellInfo, useUpdateState } from "../shell";

const fmtWhen = (t: number | null) => (t ? new Date(t).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "아직 안 함");

export function Settings() {
  const { health, activeJob, toast, fail, refreshHealth } = useApp();
  const st = useUpdateState();
  const [info, reloadInfo] = useShellInfo([st?.lastCheck, st?.applying]);
  const [checking, setChecking] = useState(false);
  const running = !!activeJob && (activeJob.status === "running" || activeJob.status === "queued");

  const check = async () => {
    if (!shell) return;
    setChecking(true);
    try { await shell.update.check(); reloadInfo(); toast("업데이트 확인 완료"); } catch (e) { fail(e); } finally { setChecking(false); }
  };

  return (
    <div className="two">
      <div>
        <Card title="버전">
          <table className="data">
            <tbody>
              <tr><td>엔진</td><td className="num">{health?.engine_version ?? "-"}</td><td className="muted xs">python · clipforge/</td></tr>
              <tr><td>화면</td><td className="num">{pkg.version}</td><td className="muted xs">React · app/dist</td></tr>
              {info && <tr><td>앱 (껍데기)</td><td className="num">{info.shellVersion}</td><td className="muted xs">Electron {shell?.versions.electron} · {info.packaged ? "설치본" : "개발"} · 모드 {info.mode}</td></tr>}
              {info && Object.entries(info.versions.components).map(([k, v]) => (
                <tr key={k}><td>{COMPONENT_LABEL[k] || k}</td><td className="num">{v}</td><td className="muted xs">런타임 구성요소</td></tr>
              ))}
            </tbody>
          </table>
          {!inShell && <p className="muted xs" style={{ marginTop: 10 }}>브라우저로 열려 있습니다. 껍데기·런타임 버전과 업데이트는 데스크톱 앱에서 보입니다.</p>}
        </Card>

        <Card title="업데이트" right={inShell && <Button size="sm" onClick={check} disabled={checking || !!st?.checking}>{checking || st?.checking ? "확인 중…" : "지금 확인"}</Button>}>
          {!inShell ? <Empty title="데스크톱 앱에서만" /> : !st ? <span className="muted small">상태 읽는 중…</span> : (
            <>
              <div className="row small" style={{ marginBottom: 8 }}>
                <span className="muted">마지막 확인 {fmtWhen(st.lastCheck)}</span>
                {st.error && st.error !== "dev" && <Badge tone="bad">실패</Badge>}
                {st.error === "dev" && <Badge>개발 모드 — 확인 안 함</Badge>}
                {!st.error && !st.pending.length && !st.shell && st.lastCheck && <Badge tone="ok">최신</Badge>}
              </div>
              {st.error && st.error !== "dev" && <p className="small" style={{ color: "var(--bad)", marginBottom: 8 }}>{st.error}</p>}
              {st.pending.length > 0 && (
                <ul className="ulist">
                  {st.pending.map((p) => (
                    <li key={p.name}><b>{COMPONENT_LABEL[p.name] || p.name}</b> <span className="mono">{p.version}</span> <span className="muted">{human(p.size)} · {p.reason === "missing" ? "미설치" : "업데이트"}</span>{p.notes && <div className="muted xs">{p.notes}</div>}</li>
                  ))}
                </ul>
              )}
              {st.shell && <p className="small">앱(껍데기) <b>{st.shell.version}</b> 을 내려받았습니다. 다음 종료 때 자동으로 설치되거나, 지금 설치하고 다시 시작할 수 있습니다.</p>}
              <div className="row" style={{ marginTop: 10 }}>
                {st.pending.length > 0 && <Button variant="primary" size="sm" disabled={running || st.applying} onClick={() => shell!.update.apply().catch(fail)}>{st.applying ? "적용 중…" : "지금 적용 (엔진 재시작)"}</Button>}
                {st.shell && <Button size="sm" disabled={running || st.applying} onClick={() => shell!.update.applyShell().catch(fail)}>설치하고 다시 시작</Button>}
                {running && <span className="muted xs">작업이 끝나면 적용할 수 있습니다</span>}
              </div>
              {info && (
                <p className="muted xs" style={{ marginTop: 10 }}>
                  서버 {info.updateUrl}{info.isPrivate && <> · 비공개 저장소 · 토큰 <span className={cx(info.hasToken ? "ok" : "bad")}>{info.hasToken ? "있음" : "없음"}</span></>}
                </p>
              )}
            </>
          )}
        </Card>
      </div>

      <div>
        <Card title="폴더">
          {!inShell || !info ? <p className="muted small">데이터 {health?.data_root ?? "-"}</p> : (
            <table className="data">
              <tbody>
                <tr><td>데이터</td><td className="mono xs">{info.dataRoot || health?.data_root}</td><td><Button size="sm" variant="ghost" onClick={() => shell!.shell.openPath(info.dataRoot || health?.data_root || "")}>열기</Button></td></tr>
                {info.runtimeDir && <tr><td>런타임</td><td className="mono xs">{info.runtimeDir}</td><td><Button size="sm" variant="ghost" onClick={() => shell!.shell.openPath(info.runtimeDir!)}>열기</Button></td></tr>}
                <tr><td>로그</td><td className="mono xs">{info.logDir}</td><td><Button size="sm" variant="ghost" onClick={() => shell!.shell.openLogs()}>열기</Button></td></tr>
              </tbody>
            </table>
          )}
          <p className="muted xs" style={{ marginTop: 10 }}>영상·캐시·라벨은 데이터 폴더에, 파이썬·모델은 런타임 폴더에 있습니다. 앱을 지워도 둘 다 남습니다.</p>
        </Card>

        <Card title="환경 진단" right={<Button size="sm" variant="ghost" onClick={() => refreshHealth().catch(fail)}>↻</Button>}>
          {!health ? <span className="muted small">읽는 중…</span> : (
            <>
              <table className="data">
                <tbody>
                  {([["ffmpeg", health.ffmpeg_ok, health.ffmpeg || ""], ["NVENC", health.nvenc, "GPU 인코딩"], ["GPU", !!health.gpu, health.gpu || "없음"], ["Whisper GPU", health.whisper_gpu, "CUDA 전사"], ["OCR", health.rapidocr, "RapidOCR"], ["폰트", health.fonts_ok, "assets/fonts"], ["디스크 여유", (health.disk_free_gb ?? 0) >= 10, `${health.disk_free_gb ?? "-"}GB`]] as [string, boolean, string][]).map(([k, ok, d]) => (
                    <tr key={k}><td>{k}</td><td><Badge tone={ok ? "ok" : "bad"}>{ok ? "OK" : "없음"}</Badge></td><td className="muted xs mono">{d}</td></tr>
                  ))}
                </tbody>
              </table>
              {health.problems.length > 0 && <ul className="ulist" style={{ marginTop: 10 }}>{health.problems.map((p) => <li key={p.code}><Badge tone={p.level === "error" ? "bad" : "warn"}>{p.level === "error" ? "오류" : "주의"}</Badge> {p.message}<div className="muted xs">{p.hint}</div></li>)}</ul>}
              <p className="muted xs" style={{ marginTop: 10 }}>엔진 로그 {health.log_path}</p>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
