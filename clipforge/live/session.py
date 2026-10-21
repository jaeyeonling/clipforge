"""라이브 세션: 캡처 루프(스레드) → 감지 → 이벤트/제안/북마크 → 파일 + 리스너(UI).

  s = LiveSession(project, config, on_event)
  s.start(); s.mark("득템!"); s.approve(suggestion_id); s.stop()

config = {
  "source": "screen"|"frames"|"video", ... (source.make_source 참고),
  "interval": 1.0,                 # 초. 화면 캡처 주기 (CPU 1장/초 수준)
  "game": "d2r",
  "approval": True,                # 제안을 바로 배너에 넣지 않고 승인 기다림 (기본 ON — 오탐이 방송에 나가는 게 최대 리스크)
  "banner_prefix": "득템 : ",
  "obs": {"url": "ws://127.0.0.1:4455", "password": "", "text_source": "득템 배너"} | None,
  "chat_roi": [x, y, w, h] 비율 | None (프로필 rois.chat), "chat_burst_thr": 0.12,
  "replay_on_approve": False       # 승인 때 OBS 리플레이 버퍼 저장
}
파일: <data>/live/<session_id>/events.jsonl · bookmarks.json · banner.txt · suggestions.json
시각: t_wall(epoch) + t_rec(OBS 녹화 타임코드 초, 연결돼 있을 때) → 방송 후 원본 VOD 와 1:1.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .detect import LabelOCR, chat_activity, drop_labels
from .source import make_source

DEFAULTS = {
    "interval": 1.0,
    "game": "d2r",
    "approval": True,
    "banner_prefix": "득템 : ",
    "chat_burst_thr": 0.12,
    "chat_cooldown": 20.0,
    "label_cooldown": 90.0,
    "replay_on_approve": False,
    "min_ocr_score": 0.6,
}


@dataclass
class Suggestion:
    id: str
    t_wall: float
    t_rec: float | None
    grade: str
    text: str
    head: str
    score: float
    status: str = "pending"  # pending | approved | dismissed
    bbox: list = field(default_factory=list)


class LiveSession:
    def __init__(self, project, config: dict, on_event: Callable[[dict], None] | None = None):
        self.project = project
        self.cfg = {**DEFAULTS, **(config or {})}
        self.on_event = on_event or (lambda e: None)
        self.id = time.strftime("%Y%m%d-%H%M%S")
        self.dir = Path(project.data_root) / "live" / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.started = 0.0
        self.frames = 0
        self.last_frame_t = 0.0
        self.last_error: str | None = None
        self.suggestions: list[Suggestion] = []
        self.bookmarks: list[dict] = []
        self.banner_items: list[str] = []
        self.obs = None
        self.obs_info: dict | None = None
        self._ocr: LabelOCR | None = None
        self._chat_prev = None
        self._last_chat_mark = 0.0
        self._last_label_t: dict[str, float] = {}
        self._lock = threading.Lock()
        # 기존 배너 텍스트 (OBS 에서 읽거나 설정)
        if self.cfg.get("banner_text"):
            self.banner_items = [
                x.strip()
                for x in str(self.cfg["banner_text"]).replace(self.cfg["banner_prefix"], "").split(",")
                if x.strip()
            ]

    # ---- 상태 ----
    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def status(self) -> dict:
        return {
            "id": self.id,
            "running": self.running,
            "started": self.started,
            "frames": self.frames,
            "last_frame_t": self.last_frame_t,
            "source": self.cfg.get("source"),
            "interval": self.cfg.get("interval"),
            "approval": self.cfg.get("approval"),
            "obs": self.obs_info,
            "obs_connected": bool(self.obs and self.obs.connected),
            "banner": self.banner_text(),
            "pending": sum(1 for s in self.suggestions if s.status == "pending"),
            "bookmarks": len(self.bookmarks),
            "last_error": self.last_error,
            "dir": str(self.dir),
        }

    def banner_text(self) -> str:
        return self.cfg["banner_prefix"] + ",".join(self.banner_items) if self.banner_items else ""

    # ---- 수명 ----
    def start(self) -> dict:
        if self.running:
            return self.status()
        self._stop.clear()
        obs_cfg = self.cfg.get("obs")
        if obs_cfg and obs_cfg.get("url"):
            try:
                from .obs import ObsClient

                self.obs = ObsClient(obs_cfg["url"], obs_cfg.get("password", ""))
                self.obs_info = self.obs.connect()
                src = obs_cfg.get("text_source")
                if src and not self.banner_items:
                    cur = self.obs.get_text(src)
                    self.banner_items = [
                        x.strip() for x in cur.replace(self.cfg["banner_prefix"], "").split(",") if x.strip()
                    ]
            except Exception as e:
                self.obs = None
                self.obs_info = {"error": str(e)[:200]}
                self._emit({"type": "warn", "message": f"OBS 연결 실패: {str(e)[:120]} — 배너 자동 갱신 없이 진행"})
        self.started = time.time()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="live")
        self._thread.start()
        self._emit({"type": "started", **self.status()})
        return self.status()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self.obs:
            self.obs.close()
            self.obs = None
        self._save()
        self._emit({"type": "stopped", **self.status()})
        return self.status()

    # ---- 사용자 동작 ----
    def mark(self, note: str = "", kind: str = "manual") -> dict:
        b = {"id": uuid.uuid4().hex[:8], "t_wall": time.time(), "t_rec": self._rec_time(), "kind": kind, "note": note}
        with self._lock:
            self.bookmarks.append(b)
        self._emit({"type": "bookmark", **b})
        self._save()
        return b

    def approve(self, sid: str, text: str | None = None) -> dict:
        s = self._find(sid)
        if s.status == "approved":
            return asdict(s)
        s.status = "approved"
        item = (text or s.head or s.text).strip()
        if item and item not in self.banner_items:
            self.banner_items.append(item)
        self._push_banner()
        self.mark(f"득템 {item}", kind="drop")
        if self.cfg.get("replay_on_approve") and self.obs:
            try:
                self.obs.save_replay_buffer()
            except Exception as e:
                self._emit({"type": "warn", "message": f"리플레이 저장 실패: {e}"})
        self._emit({"type": "suggestion", **asdict(s)})
        return asdict(s)

    def dismiss(self, sid: str) -> dict:
        s = self._find(sid)
        s.status = "dismissed"
        self._emit({"type": "suggestion", **asdict(s)})
        self._save()
        return asdict(s)

    def set_banner(self, items: list[str]) -> str:
        self.banner_items = [x.strip() for x in items if x.strip()]
        self._push_banner()
        return self.banner_text()

    # ---- 내부 ----
    def _profile_grades(self) -> tuple[str, ...]:
        try:
            from ..profiles import load_profile

            g = (load_profile(self.cfg.get("game", "d2r")).get("live") or {}).get("grades")
            return tuple(g) if g else ("set", "unique")
        except Exception:
            return ("set", "unique")

    def _find(self, sid: str) -> Suggestion:
        for s in self.suggestions:
            if s.id == sid:
                return s
        raise KeyError(sid)

    def _rec_time(self) -> float | None:
        if not self.obs:
            return None
        try:
            st = self.obs.record_status()
            return st.get("outputDuration", 0) / 1000.0 if st.get("outputActive") else None
        except Exception:
            return None

    def _push_banner(self) -> None:
        txt = self.banner_text()
        (self.dir / "banner.txt").write_text(txt, encoding="utf-8")
        obs_cfg = self.cfg.get("obs") or {}
        if self.obs and obs_cfg.get("text_source"):
            try:
                self.obs.set_text(obs_cfg["text_source"], txt)
            except Exception as e:
                self._emit({"type": "warn", "message": f"OBS 텍스트 갱신 실패: {e}"})
        self._emit({"type": "banner", "text": txt, "items": list(self.banner_items)})
        self._save()

    def _save_preview(self, frame) -> None:
        """캡처가 게임 화면을 잡고 있는지 사람이 보게 — 작은 JPEG 하나를 세션 폴더에 계속 덮어쓴다."""
        try:
            w = 640
            im = frame.resize((w, max(1, int(frame.height * w / frame.width))))
            tmp = self.dir / "last.tmp.jpg"
            im.save(tmp, "JPEG", quality=70)
            tmp.replace(self.dir / "last.jpg")
        except Exception:
            pass

    def latest_pending(self):
        for s in reversed(self.suggestions):
            if s.status == "pending":
                return s
        return None

    def _emit(self, ev: dict) -> None:
        ev = {"session": self.id, "t": round(time.time(), 3), **ev}
        try:
            with open(self.dir / "events.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass
        try:
            self.on_event({"type": "live", "event": ev})
        except Exception:
            pass

    def _save(self) -> None:
        with self._lock:
            (self.dir / "bookmarks.json").write_text(
                json.dumps(self.bookmarks, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            (self.dir / "suggestions.json").write_text(
                json.dumps([asdict(s) for s in self.suggestions], ensure_ascii=False, indent=1), encoding="utf-8"
            )

    def _loop(self) -> None:
        try:
            src = make_source(self.cfg, self.project)
        except Exception as e:
            self.last_error = f"소스 열기 실패: {e}"
            self._emit({"type": "error", "message": self.last_error})
            return
        chat_roi = self.cfg.get("chat_roi")
        if chat_roi is None:
            try:
                from ..profiles import load_profile

                chat_roi = load_profile(self.cfg.get("game", "d2r")).get("rois", {}).get("chat")
            except Exception:
                chat_roi = None
        interval = float(self.cfg["interval"])
        try:
            while not self._stop.is_set():
                t0 = time.time()
                try:
                    fr = src.next_frame()
                except Exception as e:
                    self.last_error = f"캡처 실패: {e}"
                    self._emit({"type": "error", "message": self.last_error})
                    time.sleep(interval)
                    continue
                if fr is None:
                    self._emit({"type": "info", "message": "소스 끝 (파일 재생 완료)"})
                    break
                t_wall, frame = fr
                self.frames += 1
                self.last_frame_t = t_wall
                if self.frames % max(1, int(self.cfg.get("preview_every", 2))) == 1:
                    self._save_preview(frame)
                self._process(frame, t_wall, chat_roi)
                if self.frames % 60 == 0:
                    self._emit({"type": "heartbeat", "frames": self.frames})
                dt = time.time() - t0
                if src.name == "screen" or self.cfg.get("realtime"):
                    self._stop.wait(max(0.05, interval - dt))
        finally:
            src.close()

    def _process(self, frame, t_wall: float, chat_roi) -> None:
        # 1) 바닥 아이템 라벨 (세트·유니크 기본, 희귀는 옵션)
        grades = tuple(self.cfg.get("grades") or self._profile_grades())
        labels = drop_labels(frame, grades=grades)
        if labels:
            if self._ocr is None:
                self._ocr = LabelOCR(self.cfg.get("game", "d2r"))
            for l in labels[:4]:
                self._ocr.read(frame, l)
                if not l.text or l.score < float(self.cfg["min_ocr_score"]):
                    continue
                if len(l.text.replace(" ", "")) < 3 or (
                    not l.item.get("head") and self.cfg.get("require_lexicon", True)
                ):
                    # 사전에 없는 글자(게임 메시지·지역명 등)는 제안하지 않고 기록만 남긴다
                    self._emit(
                        {
                            "type": "label",
                            "grade": l.grade,
                            "text": l.text,
                            "score": round(l.score, 2),
                            "t_wall": t_wall,
                        }
                    )
                    continue
                key = l.item.get("head") or l.text
                if t_wall - self._last_label_t.get(key, 0) < float(self.cfg["label_cooldown"]):
                    continue
                self._last_label_t[key] = t_wall
                s = Suggestion(
                    uuid.uuid4().hex[:8],
                    t_wall,
                    self._rec_time(),
                    l.grade,
                    l.text,
                    l.item.get("head", ""),
                    l.score,
                    bbox=list(l.bbox),
                )
                self.suggestions.append(s)
                self._emit({"type": "suggestion", **asdict(s)})
                if not self.cfg.get("approval"):
                    self.approve(s.id)
                else:
                    self._save()
        # 2) 채팅 활동 → 폭주 북마크
        if chat_roi:
            act, self._chat_prev = chat_activity(self._chat_prev, frame, tuple(chat_roi))
            if act >= float(self.cfg["chat_burst_thr"]) and t_wall - self._last_chat_mark > float(
                self.cfg["chat_cooldown"]
            ):
                self._last_chat_mark = t_wall
                self.mark(f"채팅 활동 {act:.2f}", kind="chat")
