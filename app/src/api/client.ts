import type {
  CalibResult, Candidate, Episode, ErrorInfo, Health, Job, Layout, LogLine, MetricRow, Profile, StageName,
} from "./types";

/** 모든 오류 응답은 {"error": {code, message, hint, kind}} 한 형태 (server.py 예외 핸들러). 네트워크 실패도 같은 모양으로 올린다. */
export class ApiError extends Error implements ErrorInfo {
  code: string;
  hint: string;
  kind: ErrorInfo["kind"];
  status: number;
  constructor(info: Partial<ErrorInfo>, status: number) {
    super(info.message || `HTTP ${status}`);
    this.code = info.code || "E_HTTP";
    this.hint = info.hint || "";
    this.kind = info.kind || "internal";
    this.status = status;
  }
  get text(): string {
    return `${this.code} ${this.message}${this.hint ? " — " + this.hint : ""}`;
  }
}

export function toErrorInfo(e: unknown): ErrorInfo {
  if (e instanceof ApiError) return { code: e.code, message: e.message, hint: e.hint, kind: e.kind };
  if (e instanceof Error) return { code: "E_UI", message: e.message, hint: "", kind: "internal" };
  return { code: "E_UI", message: String(e), hint: "", kind: "internal" };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  } catch {
    throw new ApiError({ code: "E_OFFLINE", message: "엔진에 연결할 수 없습니다", hint: "python -m clipforge.app 이 떠 있는지 확인하세요.", kind: "user" }, 0);
  }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(body.error || { message: body.detail || r.statusText }, r.status);
  return body as T;
}

const post = <T,>(path: string, data: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(data) });
const put = <T,>(path: string, data: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(data) });

export const api = {
  health: () => request<Health>("/api/health"),
  episodes: () => request<Episode[]>("/api/episodes"),
  episode: (id: string) => request<Episode>(`/api/episodes/${encodeURIComponent(id)}`),
  addEpisode: (video_path: string, title: string, game = "d2r") => post<Episode>("/api/episodes", { video_path, title, game }),
  jobs: () => request<Job[]>("/api/jobs"),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  jobLog: (id: string, tail = 400) => request<{ job_id: string; path: string; lines: LogLine[] }>(`/api/jobs/${id}/log?tail=${tail}`),
  runJob: (episode: string, stages: StageName[], params: { layout: Layout; k: number; force: boolean }) =>
    post<Job>("/api/jobs", { episode, stages, params }),
  cancelJob: (id: string) => post<Job>(`/api/jobs/${id}/cancel`, {}),
  candidates: (id: string) => request<Candidate[]>(`/api/episodes/${encodeURIComponent(id)}/candidates`),
  decide: (id: string, c: Candidate, label: "keep" | "no" | "", reason: string) =>
    post<{ ok: boolean; labels: number }>(`/api/episodes/${encodeURIComponent(id)}/decision`, { start: c.start, end: c.end, label, reason, file: c.file || "" }),
  calibrate: (id: string) => request<CalibResult>(`/api/episodes/${encodeURIComponent(id)}/calibrate`),
  calibratePreview: (id: string, t: number, rois: Record<string, number[]> | null) =>
    post<{ url: string; t: number }>(`/api/episodes/${encodeURIComponent(id)}/calibrate/preview`, { t, rois }),
  profile: (game: string) => request<Profile>(`/api/profiles/${game}`),
  saveProfile: (game: string, rois: Record<string, number[]>) => put<{ ok: boolean; note?: string }>(`/api/profiles/${game}`, { rois }),
  metrics: () => request<MetricRow[]>("/api/metrics"),
};
