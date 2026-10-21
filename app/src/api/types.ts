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

export type StageName =
  | "prep"
  | "transcribe"
  | "subtitles"
  | "signals"
  | "candidates"
  | "align"
  | "shorts"
  | "export"
  | "xml"
  | "weaklabel"
  | "eval";
export const STAGES: StageName[] = [
  "prep",
  "transcribe",
  "subtitles",
  "signals",
  "candidates",
  "align",
  "shorts",
  "export",
  "xml",
  "weaklabel",
  "eval",
];
export const STAGE_LABEL: Record<StageName, string> = {
  prep: "영상 읽기",
  transcribe: "말을 글로",
  subtitles: "자막 파일 만들기",
  signals: "순간 신호 찾기",
  candidates: "편집 포인트 고르기",
  align: "편집본과 맞춰 정답 만들기",
  shorts: "쇼츠 후보 고르기",
  export: "세로 초안 만들기",
  xml: "Premiere 파일 만들기",
  weaklabel: "제목으로 정답 추정",
  eval: "점수 매기기",
};
/** 단계의 기술 이름 설명 (고급 설정에서 작게) */
export const STAGE_TECH: Record<StageName, string> = {
  prep: "prep · 오디오·프레임·크롭 추출",
  transcribe: "transcribe · Whisper",
  subtitles: "subtitles · SRT/VTT/VEGAS TXT",
  signals: "signals · 배너 OCR·채팅·음량·줌",
  candidates: "candidates",
  align: "align · 오디오 지문",
  shorts: "shorts · 순간 순위",
  export: "export · NVENC 렌더",
  xml: "xml · xmeml",
  weaklabel: "weaklabel",
  eval: "eval · hit@K / recall",
};
export const ANCHOR_LABEL: Record<string, string> = {
  item: "득템",
  chat: "채팅",
  zoom: "줌",
  note: "메모",
  speech: "발화",
  loud: "음량",
  motion: "움직임",
  cut: "컷",
};
export const VARIANT_LABEL: Record<string, string> = { story: "서사형 (30~45초)", short: "한방형 (15~20초)" };
export const GRADE_LABEL: Record<string, string> = { set: "세트", unique: "유니크", rare: "희귀", magic: "매직" };
export const DECISION_LABEL: Record<string, string> = { keep: "쓸 만함", no: "안 씀", kept: "정답", "": "" };
export type EpisodeKind = "edited" | "original";
export const KIND_LABEL: Record<EpisodeKind, string> = { edited: "편집본 → 쇼츠", original: "원본 → 편집 포인트" };
/** 회차 종류별 기본 단계 (jobs.DEFAULT_STAGES 와 동일) */
export const DEFAULT_STAGES: Record<EpisodeKind, StageName[]> = {
  edited: ["prep", "transcribe", "signals", "shorts", "export", "xml"],
  original: ["prep", "transcribe", "signals", "candidates", "align", "eval"],
};

export interface EditPoint {
  idx: number;
  start: number;
  end: number;
  score: number;
  label: string;
  meta: Record<string, unknown>;
  kept: boolean;
  kept_labels: string[];
  decision: "kept" | "no" | "";
}
export interface LabelCategory {
  key: string;
  label: string;
  hint?: string;
  color?: string;
  shortcut?: string;
}
export interface KeptSeg {
  start: number;
  end: number;
  label: string;
  source: "auto" | "manual" | "ui";
  note: string;
}
export interface EditPointsResult {
  episode: string;
  duration: number;
  candidates: EditPoint[];
  signals: string[];
  kept: { start: number; end: number; label: string; note: string }[];
  categories: LabelCategory[];
  report: {
    recall: number;
    precision: number;
    coverage: number;
    n_labels: number;
    n_candidates: number;
    missed: { start: number; end: number; label: string }[];
    by_label: Record<string, { hit: number; total: number }>;
  } | null;
  align: { final: string; matched_frac: number; n_segments: number; unmatched: [number, number][] } | null;
  video_url: string | null;
}

export interface Episode {
  id: string;
  kind?: EpisodeKind;
  source?: string; // 영상 실제 경로
  linked?: boolean; // videos/ 안의 링크/복사본이면 true, 원본 경로 참조면 false
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
  eta_s?: number | null;
  stage_eta?: Record<string, number>;
  warnings?: { code: string; message: string; hint: string }[];
  log_path?: string | null;
  manifest_path?: string | null;
  from_manifest?: boolean;
}

export interface EngineEvent {
  job_id: string;
  t: number;
  type: "queued" | "started" | "progress" | "log" | "done" | "error";
  episode?: string;
  stage?: string;
  pct?: number;
  message?: string;
  level?: "info" | "warn" | "error";
  status?: JobStatus;
  code?: string;
  hint?: string;
  kind?: ErrorInfo["kind"];
  stages?: string[];
  eta_s?: number | null;
  warnings?: { code: string; message: string; hint: string }[];
}

export interface PathInfo {
  path: string;
  exists: boolean;
}
export interface EpisodePaths {
  shorts_dir: PathInfo;
  premiere_review: PathInfo;
  premiere_shorts: PathInfo;
  premiere_dir: PathInfo;
  subtitles_srt: PathInfo;
  subtitles_vtt: PathInfo;
  subtitles_vegas: PathInfo;
  subtitles_dir: PathInfo;
  cache_dir: PathInfo;
  labels_shorts: PathInfo;
  labels_editpoints: PathInfo;
  data_dir: PathInfo;
  shorts_count: number;
  video: string;
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
  gt?: string[]; // 겹치는 올린 쇼츠(역매핑)·확정본 이름
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

export interface PreviewResult {
  url: string; // 서버가 박스를 그린 합성 PNG
  t: number;
  n_frames: number;
  frame_url: string; // 원본 프레임 (화면 편집기용)
  frame_size: [number, number];
  rois: Record<string, number[]>; // 비율 [x, y, w, h]
  panel_bands: Record<string, number[]>;
  colors: Record<string, string>;
}

export interface Profile {
  name?: string;
  rois: Record<string, number[]>;
  panel_bands?: Record<string, number[]>;
  [k: string]: unknown;
}

/** 판정 학습 상태 (GET /api/preference). weights 는 지금 쇼츠 순위에 쓰는 축 가중치. */
export interface Preference {
  weights: Record<PrefAxis, number>;
  default: Record<PrefAxis, number>;
  n_keep: number;
  n_no: number;
  learned: boolean;
  blend: number;
  reason: string;
  updated: string;
}
export type PrefAxis = "payoff" | "reaction" | "chat" | "completeness" | "hook";
export const PREF_AXIS_LABEL: Record<PrefAxis, string> = {
  payoff: "득템",
  reaction: "리액션",
  chat: "채팅 반응",
  completeness: "완결성",
  hook: "첫 2초",
};

export interface MetricRow {
  episode: string;
  phase: "shorts" | "editpoints";
  labels: number;
  keep?: number;
  no?: number;
  hit1?: number | null;
  hit3?: number | null;
  mrr?: number | null;
  recall?: number;
  precision?: number;
  coverage?: number;
  n_candidates?: number;
}

export interface LiveSuggestion {
  id: string;
  t_wall: number;
  t_rec: number | null;
  grade: string;
  text: string;
  head: string;
  score: number;
  status: "pending" | "approved" | "dismissed";
  bbox: number[];
}
export interface LiveBookmark {
  id: string;
  t_wall: number;
  t_rec: number | null;
  kind: string;
  note: string;
}
export interface LiveSession {
  id: string;
  running: boolean;
  started: number;
  frames: number;
  last_frame_t: number;
  source: string;
  interval: number;
  approval: boolean;
  obs: Record<string, unknown> | null;
  obs_connected: boolean;
  banner: string;
  pending: number;
  bookmarks: number;
  last_error: string | null;
  dir: string;
}
export interface LiveStatus {
  active: boolean;
  session: LiveSession | null;
  suggestions: LiveSuggestion[];
  bookmarks: LiveBookmark[];
  preview_url?: string | null;
}
export interface GameInfo {
  key: string;
  name: string;
}
export type LiveEvent = { session: string; t: number; type: string; [k: string]: unknown };

export type Layout = "card" | "feed";
export const REASONS = ["재미없음", "임팩트없음", "중복", "잘림", "맥락없음", "기타"] as const;
