import { useState } from "react";
import { Button, cx } from "../components/ui";
import { useApp } from "../state/store";
import { COMPONENT_LABEL, human, shell, useUpdateState } from "../shell";

const SEEN_KEY = "cf.updatePromptSeen";

/** 업데이트가 있거나 적용 중일 때만 탭 위에 한 줄. 적용은 항상 사용자가 누른다. 작업 중엔 잠근다. */
export function UpdateBanner({ onSettings }: { onSettings: () => void }) {
  const st = useUpdateState();
  const { activeJob, fail } = useApp();
  const [seen, setSeen] = useState<string>(() => {
    try {
      return localStorage.getItem(SEEN_KEY) || "";
    } catch {
      return "";
    }
  });
  const sh = shell;
  if (!sh || !st) return null;
  const running = !!activeJob && (activeJob.status === "running" || activeJob.status === "queued");
  const total = st.pending.reduce((a, p) => a + p.size, 0);

  if (st.applying) {
    const p = st.progress;
    return (
      <div className="ubanner applying">
        <span className="spinner" />
        <span>
          업데이트 적용 중
          {p ? ` — ${COMPONENT_LABEL[p.name] || p.name} ${p.total ? Math.round((100 * p.done) / p.total) : 0}%` : ""}
        </span>
        {p && p.total > 0 && (
          <div className="ubar">
            <i style={{ width: `${Math.round((100 * p.done) / p.total)}%` }} />
          </div>
        )}
      </div>
    );
  }
  if (!st.pending.length && !st.shell) return null;
  // 새 버전을 처음 봤을 때 한 번만 시트로 묻는다: 지금 적용 / 나중에. '나중에'를 누르면 배너만 남는다.
  const key = `${st.pending.map((p) => `${p.name}@${p.version}`).join(",")}|${st.shell?.version || ""}`;
  const later = () => {
    setSeen(key);
    try {
      localStorage.setItem(SEEN_KEY, key);
    } catch {
      /* ignore */
    }
  };
  const applyNow = () => {
    later();
    (st.pending.length ? sh.update.apply() : sh.update.applyShell()).catch(fail);
  };
  const askNow = seen !== key && !running;
  return (
    <>
      {askNow && (
        <div className="sheet" role="dialog" aria-label="업데이트">
          <h3>새 버전이 준비됐어요</h3>
          <div className="sub">
            {st.pending.length > 0 && (
              <>
                {st.pending.map((p) => `${COMPONENT_LABEL[p.name] || p.name} ${p.version}`).join(", ")} ({human(total)})
                — 내려받고 엔진을 다시 시작해요. 보통 1분 안에 끝나요.
              </>
            )}
            {st.pending.length > 0 && st.shell && <br />}
            {st.shell && <>앱 {st.shell.version} — 이미 내려받았어요. 설치하고 다시 시작해요.</>}
          </div>
          <div className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
            <Button variant="ghost" onClick={later}>
              나중에
            </Button>
            <Button variant="primary" onClick={applyNow}>
              {st.pending.length ? "지금 적용하고 다시 시작" : "설치하고 다시 시작"}
            </Button>
          </div>
        </div>
      )}
      <div className={cx("ubanner")}>
        <span className="dot" />
        <span className="grow">
          {st.pending.length > 0 && (
            <>
              업데이트 있음 — {st.pending.map((p) => `${COMPONENT_LABEL[p.name] || p.name} ${p.version}`).join(", ")}{" "}
              <span className="muted">({human(total)})</span>
            </>
          )}
          {st.pending.length > 0 && st.shell && " · "}
          {st.shell && (
            <>
              앱 {st.shell.version} 준비됨 <span className="muted">(설치하려면 다시 시작)</span>
            </>
          )}
        </span>
        {running && <span className="muted xs">작업이 끝나면 적용할 수 있어요</span>}
        {st.pending.length > 0 && (
          <Button size="sm" variant="primary" disabled={running} onClick={() => sh.update.apply().catch(fail)}>
            지금 적용
          </Button>
        )}
        {st.shell && (
          <Button size="sm" disabled={running} onClick={() => sh.update.applyShell().catch(fail)}>
            설치하고 다시 시작
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={onSettings}>
          자세히
        </Button>
      </div>
    </>
  );
}
