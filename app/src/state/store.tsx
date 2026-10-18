import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, toErrorInfo } from "../api/client";
import { useEngineEvents } from "../api/ws";
import type { EngineEvent, Episode, ErrorInfo, Health, Job, LogLine, StageName } from "../api/types";

export interface Toast { id: number; text: string; bad: boolean }
export type JobParams = Parameters<typeof api.runJob>[2];
export interface RunError { info: ErrorInfo; job: Pick<Job, "id" | "episode" | "stages" | "params"> | null }

interface Store {
  health: Health | null;
  episodes: Episode[];
  selected: Episode | null;
  selectEpisode: (id: string) => void;
  jobs: Job[];
  activeJob: Job | null;          // 지금 돌고 있는(또는 방금 끝난) 작업
  viewJobId: string | null;       // 로그 창에 보이는 작업
  log: LogLine[];
  logTitle: string;
  logPath: string;
  runError: RunError | null;
  wsConnected: boolean;
  tick: number;                   // 데이터가 바뀌었을 때 증가 → 후보·지표 다시 읽기
  toasts: Toast[];
  toast: (text: string, bad?: boolean) => void;
  fail: (e: unknown) => void;
  refreshHealth: () => Promise<void>;
  refreshEpisodes: () => Promise<void>;
  refreshJobs: () => Promise<void>;
  addEpisode: (path: string, title: string) => Promise<void>;
  runJob: (episode: string, stages: StageName[], params: JobParams) => Promise<void>;
  cancelJob: () => Promise<void>;
  viewJob: (id: string) => Promise<void>;
  clearLog: () => void;
  dismissError: () => void;
}

const Ctx = createContext<Store | null>(null);
const LS_KEY = "cf.episode";

export function AppProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(() => localStorage.getItem(LS_KEY));
  const [jobs, setJobs] = useState<Job[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [viewJobId, setViewJobId] = useState<string | null>(null);
  const [log, setLog] = useState<LogLine[]>([]);
  const [logTitle, setLogTitle] = useState("로그");
  const [logPath, setLogPath] = useState("");
  const [runError, setRunError] = useState<RunError | null>(null);
  const [tick, setTick] = useState(0);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastSeq = useRef(0);

  const toast = useCallback((text: string, bad = false) => {
    const id = ++toastSeq.current;
    setToasts((ts) => [...ts.slice(-3), { id, text, bad }]);
    window.setTimeout(() => setToasts((ts) => ts.filter((t) => t.id !== id)), bad ? 6000 : 3200);
  }, []);
  const fail = useCallback((e: unknown) => {
    console.error(e);
    const info = toErrorInfo(e);
    toast(`${info.code} ${info.message}${info.hint ? " — " + info.hint : ""}`, true);
  }, [toast]);

  const refreshHealth = useCallback(async () => setHealth(await api.health()), []);
  const refreshEpisodes = useCallback(async () => {
    const eps = await api.episodes();
    setEpisodes(eps);
    setSelectedId((cur) => (cur && eps.some((e) => e.id === cur) ? cur : eps[0]?.id ?? null));
  }, []);
  const refreshJobs = useCallback(async () => setJobs(await api.jobs()), []);

  const selectEpisode = useCallback((id: string) => { setSelectedId(id); localStorage.setItem(LS_KEY, id); }, []);
  const selected = useMemo(() => episodes.find((e) => e.id === selectedId) ?? null, [episodes, selectedId]);
  const activeJob = useMemo(() => jobs.find((j) => j.id === activeJobId) ?? null, [jobs, activeJobId]);

  const addEpisode = useCallback(async (path: string, title: string) => {
    const ep = await api.addEpisode(path, title);
    toast(`등록: ${ep.id}`);
    await refreshEpisodes();
    selectEpisode(ep.id);
  }, [refreshEpisodes, selectEpisode, toast]);

  const clearLog = useCallback(() => { setLog([]); setLogTitle("로그"); setLogPath(""); }, []);
  const dismissError = useCallback(() => setRunError(null), []);

  const runJob = useCallback(async (episode: string, stages: StageName[], params: JobParams) => {
    const j = await api.runJob(episode, stages, params);
    setActiveJobId(j.id); setViewJobId(j.id); setRunError(null);
    setLog([]); setLogTitle(`${episode} · ${j.id}`); setLogPath(j.log_path || "");
    toast(`작업 시작: ${stages.join(" → ")}`);
    await refreshJobs();
  }, [refreshJobs, toast]);

  const cancelJob = useCallback(async () => {
    if (!activeJobId) return;
    await api.cancelJob(activeJobId);
    await refreshJobs();
  }, [activeJobId, refreshJobs]);

  const viewJob = useCallback(async (id: string) => {
    const [j, lg] = await Promise.all([api.job(id), api.jobLog(id)]);
    setViewJobId(id);
    setLog(lg.lines.map((l) => ({ ...l, level: l.level === "error" ? "error" : l.type === "done" ? "done" : l.level })));
    setLogTitle(`${j.episode} · ${j.id}`); setLogPath(lg.path);
    if (j.status === "error" && j.error_info) setRunError({ info: j.error_info, job: j }); else setRunError(null);
    if (j.status === "running" || j.status === "queued") setActiveJobId(id);
  }, []);

  // ---- 이벤트 (WebSocket) ----
  const onEvent = useCallback((ev: EngineEvent) => {
    const mine = ev.job_id === activeJobId || ev.job_id === viewJobId;
    if (ev.type === "log" && mine) {
      setLog((l) => [...l.slice(-800), { t: ev.t, type: "log", stage: ev.stage || "", level: ev.level || "info", message: ev.message || "" }]);
    }
    if (ev.type === "progress" && mine) {
      setJobs((js) => js.map((j) => (j.id === ev.job_id ? { ...j, status: "running", stage: ev.stage || j.stage, pct: ev.pct ?? j.pct, message: ev.message || "" } : j)));
    }
    if (ev.type === "done" || ev.type === "error") {
      if (ev.type === "error" && mine) {
        const info: ErrorInfo = { code: ev.code || "E_INTERNAL", message: ev.message || "", hint: ev.hint || "", kind: ev.kind || "internal" };
        setLog((l) => [...l, { t: ev.t, type: "error", stage: ev.stage || "", level: "error", message: `${info.code}: ${info.message}${info.hint ? "\n→ " + info.hint : ""}` }]);
        setRunError({ info, job: jobs.find((j) => j.id === ev.job_id) ?? null });
        toast(`오류 ${info.code}: ${info.message}`, true);
      } else if (mine) {
        setLog((l) => [...l, { t: ev.t, type: "done", stage: "", level: "done", message: ev.status === "cancelled" ? "취소됨" : "완료" }]);
        toast(ev.status === "cancelled" ? "취소됨" : "완료");
      }
      setTick((n) => n + 1);
      refreshJobs().catch(() => {});
      refreshEpisodes().catch(() => {});
    }
    if (ev.type === "queued" || ev.type === "started") refreshJobs().catch(() => {});
  }, [activeJobId, viewJobId, jobs, refreshJobs, refreshEpisodes, toast]);
  const { connected: wsConnected } = useEngineEvents(onEvent);

  useEffect(() => {
    refreshHealth().catch(fail);
    refreshEpisodes().catch(fail);
    refreshJobs().then(() => undefined).catch(fail);
  }, [refreshHealth, refreshEpisodes, refreshJobs, fail]);
  useEffect(() => {
    // 연결이 돌아오면 상태를 다시 맞춘다
    if (wsConnected) { refreshJobs().catch(() => {}); refreshHealth().catch(() => {}); }
  }, [wsConnected, refreshJobs, refreshHealth]);
  useEffect(() => {
    // 새로고침 직후 돌고 있는 작업이 있으면 그걸 활성으로
    if (!activeJobId) { const r = jobs.find((j) => j.status === "running" || j.status === "queued"); if (r) setActiveJobId(r.id); }
  }, [jobs, activeJobId]);

  const value: Store = {
    health, episodes, selected, selectEpisode, jobs, activeJob, viewJobId, log, logTitle, logPath, runError, wsConnected, tick, toasts,
    toast, fail, refreshHealth, refreshEpisodes, refreshJobs, addEpisode, runJob, cancelJob, viewJob, clearLog, dismissError,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("AppProvider missing");
  return s;
}
