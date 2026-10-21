import { useEffect, useRef, useState } from "react";
import type { EngineEvent } from "./types";

/** /ws 에서 Job 이벤트를 받는다. 끊기면 1.5초 후 자동 재연결. 핸들러는 ref 로 들고 있어 재구독 없이 최신 함수를 부른다. */
export function useEngineEvents(onEvent: (ev: EngineEvent) => void): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let closed = false;
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.onopen = () => setConnected(true);
      ws.onmessage = (m) => {
        try {
          handler.current(JSON.parse(m.data) as EngineEvent);
        } catch (e) {
          console.error("bad event", e);
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) timer = window.setTimeout(connect, 1500);
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return { connected };
}
