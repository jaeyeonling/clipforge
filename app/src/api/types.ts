// 엔진 API 타입 (clipforge/api/methods.py 의 반환 형태를 그대로 옮김)

export interface ErrorInfo {
  code: string;
  message: string;
  hint: string;
  kind: "user" | "internal";
}

export interface Problem {
  level: "error" | "warn";
  code: string;
  message: string;
  hint: string;
}

export interface Health {
  engine_version: string;
  schema: Record<string, number>;
  project: Record<string, unknown>;
  schema_error: ErrorInfo | null;
  log_path: string;
  app_root: string;
  data_root: string;
  ffmpeg: string | null;
  ffmpeg_ok: boolean;
  nvenc: boolean;
  gpu: string | null;
  whisper_gpu: boolean;
  fonts_ok: boolean;
  rapidocr: boolean;
  disk_free_gb: number | null;
  problems: Problem[];
}

export type StageName = "prep" | "transcribe" | "signals" | "shorts" | "export" | "xml" | "weaklabel" | "eval";
export const STAGES: StageName[] = ["prep", "transcribe", "signals", "shorts", "export", "xml", "weaklabel", "eval"];
export const STAGE_LABEL: Record<StageName, string> = {
  prep: "준비", transcribe: "전사", signals: "신호", shorts: "후보", export: "초안 렌더", xml: "Premiere XML", weaklabel: "약한 정답", eval: "평가",
};

export interface Episode {
  id: string;
  title?: string;
  game?: string;
  duration?: number;
  width?: number;
  height?: number;
  fps?: number;
  stages: Record<string, boolean>;
}

export type JobStatus = "queued" | "running" | "done" | "error" | "cancelled";

export interface Job {
  id: string;
  episode: string;
  stages: StageName[];
  params: Record<string, unknown>;
  status: JobStatus;
  stage: string;
  pct: number;
  message: string;
  started: number;
  finished: number;
  error: string | null;
  error_info?: ErrorInfo | null;
  stage_durations?: Record<string, number>;
  log_path?: string | null;
  manifest_path?: string | null;
  from_manifest?: boolean;
}

export interface EngineEvent {
  job_id: string;
  t: number;
  type: "queued" | "started" | "progress" | "log" | "done" | "error";
  stage?: string;
  pct?: number;
  message?: string;
  level?: "info" | "warn" | "error";
  status?: JobStatus;
  code?: string;
  hint?: string;
  kind?: ErrorInfo["kind"];
  stages?: string[];
}

export interface LogLine {
  t: number | null;
  type: string;
  stage: string;
  level: "info" | "warn" | "error" | "done";
  message: string;
}

export interface Candidate {
  file?: string;
  rank?: number;
  variant: "story" | "short" | string;
  start: number;
  end: number;
  anchor: number;
  score: number;
  axes?: Record<string, number>;
  evidence?: { anchor_kinds?: string[]; n_cuts?: number; [k: string]: unknown };
  hook_mode?: string;
  overlay_text?: string;
  hook_lines?: string[];
  subtitle_cues?: number;
  top_mode?: string;
  layout?: string;
  decision?: "keep" | "no" | "";
  reason?: string;
  media_url?: string;
}

export interface CalibCheck {
  name: string;
  status: "pass" | "warn" | "fail" | "skip";
  rate: number | null;
  detail: string;
  hint?: string;
}

export interface CalibResult {
  ok: boolean;
  error?: string;
  game: string;
  resolution: [number, number];
  status: "pass" | "warn" | "fail";
  checks: CalibCheck[];
}

export interface Profile {
  name?: string;
  rois: Record<string, number[]>;
  panel_bands?: Record<string, number[]>;
  [k: string]: unknown;
}

export interface MetricRow {
  episode: string;
  labels: number;
  keep: number;
  no: number;
  hit1: number | null;
  hit3: number | null;
  mrr: number | null;
}

export type Layout = "card" | "feed";
export const REASONS = ["재미없음", "임팩트없음", "중복", "잘림", "맥락없음", "기타"] as const;
