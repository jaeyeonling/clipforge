import { useEffect, useState } from "react";
import { STAGE_LABEL, type StageName } from "./api/types";
import { TIP } from "./api/tips";
import { Progress, Tabs, Toasts } from "./components/ui";
import { useTooltips } from "./components/useTooltips";
import { Calibration } from "./features/Calibration";
import { Candidates } from "./features/Candidates";
import { EditPoints } from "./features/EditPoints";
import { Live } from "./features/Live";
import { Alerts, Header } from "./features/Header";
import { Metrics } from "./features/Metrics";
import { Pipeline } from "./features/Pipeline";
import { Settings } from "./features/Settings";
import { Sidebar } from "./features/Sidebar";
import { UpdateBanner } from "./features/UpdateBanner";
import { AppProvider, useApp } from "./state/store";

import { Help, Stepper, Welcome, type Tab } from "./features/Onboarding";
const TABS: Tab[] = ["pipeline", "candidates", "editpoints", "calibration", "metrics", "live", "settings", "help"];
/** 단순 모드에서 보이는 탭: 만들기 · 쇼츠 초안 · 설정 · 도움말 */
const SIMPLE_TABS: Tab[] = ["pipeline", "candidates", "settings", "help"];
const TAB_KEY = "cf.tab";
const hashTab = (): Tab | null => {
  const h = location.hash.replace("#", "") as Tab;
  return TABS.includes(h) ? h : null;
};

function Main() {
  const { selected, activeJob, toasts, viewJobId, runError, liveStatus, lastDone, candCount, episodes, simple } =
    useApp();
  const [chosenTab, setTab] = useState<Tab>(() => hashTab() || (localStorage.getItem(TAB_KEY) as Tab) || "pipeline");
  // 단순 모드에서 숨긴 탭을 골라 둔 상태면 만들기 탭을 보여준다 (고른 값은 그대로 두고 보이는 탭만 계산)
  const tab: Tab = simple && !SIMPLE_TABS.includes(chosenTab) ? "pipeline" : chosenTab;

  // 상황이 바뀐 그 렌더에서 한 번만 탭을 옮긴다 (effect 로 옮기면 화면을 두 번 그린다)
  // - 작업 이력을 눌렀거나 오류가 나면 파이프라인 탭(로그·오류 카드)으로
  const [seenError, setSeenError] = useState({ viewJobId, runError });
  if (seenError.viewJobId !== viewJobId || seenError.runError !== runError) {
    setSeenError({ viewJobId, runError });
    if (viewJobId && runError) setTab("pipeline");
  }
  // - 초안이 나오면 후보 탭으로, 편집 포인트가 나오면 편집 포인트 탭으로 — "완료" 뒤 뭘 할지 화면이 말한다
  const [seenDone, setSeenDone] = useState(lastDone);
  if (seenDone !== lastDone) {
    setSeenDone(lastDone);
    if (lastDone && lastDone.episode === selected?.id) {
      if (lastDone.stages.includes("export")) setTab("candidates");
      else if (!simple && (lastDone.stages.includes("candidates") || lastDone.stages.includes("align")))
        setTab("editpoints");
    }
  }

  useEffect(() => {
    localStorage.setItem(TAB_KEY, tab);
    if (location.hash !== `#${tab}`) history.replaceState(null, "", `#${tab}`);
  }, [tab]);
  useEffect(() => {
    const h = () => {
      const t = hashTab();
      if (t) setTab(t);
    };
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  // 영상은 한 번에 하나만: 어떤 <video> 가 재생을 시작하면 같은 그룹(비교 패널)이 아닌 나머지를 멈춘다
  useEffect(() => {
    const onPlay = (e: Event) => {
      const v = e.target;
      if (!(v instanceof HTMLVideoElement)) return;
      const group = v.dataset.group || "";
      document.querySelectorAll("video").forEach((o) => {
        if (o !== v && !o.paused && (!group || (o.dataset.group || "") !== group)) o.pause();
      });
    };
    document.addEventListener("play", onPlay, true);
    return () => document.removeEventListener("play", onPlay, true);
  }, []);

  const running = !!activeJob && (activeJob.status === "running" || activeJob.status === "queued");
  const allTabs: { key: Tab; label: string; count?: number | string; tip?: string }[] = [
    { key: "pipeline", label: simple ? "만들기" : "실행", tip: TIP.tabRun },
    ...(selected?.kind === "original"
      ? [
          { key: "editpoints" as Tab, label: "편집 포인트", tip: TIP.tabEdit },
          { key: "candidates" as Tab, label: "쇼츠 초안", count: candCount || undefined, tip: TIP.tabShorts },
        ]
      : [
          { key: "candidates" as Tab, label: "쇼츠 초안", count: candCount || undefined, tip: TIP.tabShorts },
          { key: "editpoints" as Tab, label: "편집 포인트", tip: TIP.tabEdit },
        ]),
    { key: "calibration", label: "화면 영역", tip: TIP.tabCalib },
    { key: "metrics", label: "기록", tip: TIP.tabRecord },
    { key: "live", label: "라이브", count: liveStatus?.active ? "●" : undefined, tip: TIP.tabLive },
    { key: "settings", label: "설정", tip: TIP.tabSettings },
    { key: "help", label: "도움말", tip: TIP.tabHelp },
  ];
  return (
    <div className="main">
      <div className="main-head">
        <h1>
          {selected
            ? selected.id
            : episodes.length
              ? simple
                ? "영상을 골라 주세요"
                : "회차를 골라 주세요"
              : "시작해 볼까요"}
        </h1>
        {selected?.title && (
          <span className="sub" title={selected.title}>
            {selected.title}
          </span>
        )}
      </div>
      <UpdateBanner onSettings={() => setTab("settings")} />
      {selected && tab !== "help" && tab !== "live" && tab !== "settings" && <Stepper onTab={setTab} />}
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        items={simple ? allTabs.filter((t) => SIMPLE_TABS.includes(t.key)) : allTabs}
      />
      <div className="content">
        {!episodes.length && tab !== "help" && tab !== "settings" && tab !== "live" && <Welcome onTab={setTab} />}
        {running && tab !== "pipeline" && (
          <div className="ticker">
            <span>
              <b>{activeJob.episode}</b> · {STAGE_LABEL[activeJob.stage as StageName] || activeJob.stage}{" "}
              {Math.round(activeJob.pct)}% {activeJob.message}
            </span>
            <Progress pct={activeJob.pct} />
          </div>
        )}
        <div hidden={tab !== "pipeline" || !episodes.length}>
          <Pipeline />
        </div>
        {tab === "candidates" && episodes.length > 0 && <Candidates />}
        {tab === "editpoints" && <EditPoints />}
        {tab === "calibration" && <Calibration />}
        {tab === "metrics" && <Metrics />}
        {tab === "live" && <Live />}
        {tab === "settings" && <Settings />}
        {tab === "help" && <Help />}
      </div>
      <Toasts items={toasts} />
    </div>
  );
}

export default function App() {
  useTooltips();
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
