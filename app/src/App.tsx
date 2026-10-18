import { useEffect, useState } from "react";
import { Progress, Tabs, Toasts, cx } from "./components/ui";
import { Calibration } from "./features/Calibration";
import { Candidates } from "./features/Candidates";
import { Alerts, Header } from "./features/Header";
import { Metrics } from "./features/Metrics";
import { Pipeline } from "./features/Pipeline";
import { Sidebar } from "./features/Sidebar";
import { AppProvider, useApp } from "./state/store";

type Tab = "candidates" | "pipeline" | "calibration" | "metrics";
const TAB_KEY = "cf.tab";

function Main() {
  const { selected, activeJob, toasts, viewJobId, runError } = useApp();
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem(TAB_KEY) as Tab) || "pipeline");
  useEffect(() => localStorage.setItem(TAB_KEY, tab), [tab]);
  // 작업 이력을 눌렀거나 오류가 나면 파이프라인 탭(로그·오류 카드)으로
  useEffect(() => { if (viewJobId && tab !== "pipeline" && runError) setTab("pipeline"); /* eslint-disable-line */ }, [runError, viewJobId]);

  const running = !!activeJob && (activeJob.status === "running" || activeJob.status === "queued");
  return (
    <div className="main">
      <div className="main-head">
        <h1>{selected ? selected.id : "회차를 선택하세요"}</h1>
        {selected?.title && <span className="sub" title={selected.title}>{selected.title}</span>}
      </div>
      <Tabs<Tab> value={tab} onChange={setTab} items={[
        { key: "pipeline", label: "파이프라인" },
        { key: "candidates", label: "후보" },
        { key: "calibration", label: "캘리브레이션" },
        { key: "metrics", label: "지표 · 작업" },
      ]} />
      <div className="content">
        {running && tab !== "pipeline" && (
          <div className="ticker"><span><b>{activeJob.episode}</b> · {activeJob.stage} {Math.round(activeJob.pct)}% {activeJob.message}</span><Progress pct={activeJob.pct} /></div>
        )}
        <div className={cx(tab !== "pipeline" && "hidden")} hidden={tab !== "pipeline"}><Pipeline /></div>
        {tab === "candidates" && <Candidates />}
        {tab === "calibration" && <Calibration />}
        {tab === "metrics" && <Metrics />}
      </div>
      <Toasts items={toasts} />
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <div className="app">
        <Header />
        <Alerts />
        <div className="body">
          <Sidebar />
          <Main />
        </div>
      </div>
    </AppProvider>
  );
}
