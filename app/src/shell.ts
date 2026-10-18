// Electron 껍데기 브리지 (desktop/preload.js 의 window.clipforgeShell). 브라우저로 열면 없다 → 모든 훅이 null 을 돌려준다.
import { useCallback, useEffect, useState } from "react";

export interface UpdatePending { name: string; version: string; size: number; reason: "missing" | "update"; notes?: string }
export interface UpdateState {
  checking: boolean; applying: boolean; lastCheck: number | null; error: string | null;
  progress: { name: string; done: number; total: number } | null;
  pending: UpdatePending[]; shell: { version: string } | null;
}
export interface ShellInfo {
  mode: string; runtimeDir: string | null; dataRoot: string | null; logDir: string; updateUrl: string; isPrivate: boolean; hasToken: boolean;
  shellVersion: string; packaged: boolean; versions: { engine: string | null; components: Record<string, string> };
}
interface ShellApi {
  platform: string;
  versions: { electron: string; node: string; chrome: string };
  update: { state: () => Promise<UpdateState>; onState: (cb: (s: UpdateState) => void) => () => void; check: () => Promise<unknown>; apply: () => Promise<void>; applyShell: () => Promise<void> };
  shell: {
    info: () => Promise<ShellInfo>; openLogs: () => Promise<void>; openPath: (p: string) => Promise<void>;
    pickVideos: () => Promise<string[]>; pathForFile: (f: File) => string;
  };
}
declare global { interface Window { clipforgeShell?: ShellApi } }

export const shell: ShellApi | null = typeof window !== "undefined" && window.clipforgeShell ? window.clipforgeShell : null;
export const inShell = !!shell;

export function useUpdateState(): UpdateState | null {
  const [st, setSt] = useState<UpdateState | null>(null);
  useEffect(() => {
    if (!shell) return;
    shell.update.state().then(setSt).catch(() => {});
    return shell.update.onState(setSt);
  }, []);
  return st;
}

export function useShellInfo(deps: unknown[] = []): [ShellInfo | null, () => void] {
  const [info, setInfo] = useState<ShellInfo | null>(null);
  const reload = useCallback(() => { shell?.shell.info().then(setInfo).catch(() => {}); }, []);
  useEffect(() => { reload(); }, [reload, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps
  return [info, reload];
}

export const human = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)}GB` : n >= 1e6 ? `${Math.round(n / 1e6)}MB` : `${Math.round(n / 1e3)}KB`);
export const COMPONENT_LABEL: Record<string, string> = {
  engine_code: "앱 코드 (엔진·화면)", "python-base": "파이썬 런타임", cuda: "GPU 가속 (CUDA)", ffmpeg: "FFmpeg", whisper: "음성 인식 모델",
};
