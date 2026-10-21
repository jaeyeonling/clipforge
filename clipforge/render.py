"""쇼츠 초안 렌더 (L4, Phase 1).

shorts.json 의 후보를 1080×1920 세로 초안 mp4 로 뽑는다. Premiere 전에 "눈으로 보고 고르기" 용도라 화질보다 속도.
레이아웃(한국 클립 채널 A형 단순화, docs/research/shorts_formula.md):
  상단 400px  검은 띠 + 훅 텍스트 2줄 (지금은 배너 OCR 원문/시각. 8단계 사전 뒤 아이템명·가치로 교체)
  중단 1080px 게임 화면 정사각 크롭 (기본 중앙. --cx 로 중심 이동. 툴팁 추적은 후속)
  하단 440px  채팅 오버레이 ROI 확대 (한국 쇼츠의 채팅 스크린샷 관례)
NVDEC 디코딩 → NVENC 인코딩. 실패 시 libx264. 폰트는 맑은 고딕 Bold.
"""

from __future__ import annotations

import itertools
import re
import subprocess
from pathlib import Path

from .schema import write_json
from .shorts import ShortCandidate, clean_chat
from .timeline import fmt_time

FONT = "C\\:/Windows/Fonts/malgunbd.ttf"  # ffmpeg 필터 안에서 'C:' 콜론은 백슬래시 하나로 이스케이프 (C\:)
TOP_H, GAME_H, CHAT_H = 400, 1080, 440


def _clean(text: str, limit: int = 22) -> str:
    text = re.sub(r"^(득템|득렘|득램|특템|특램|템|렘)", "", text)
    text = re.sub(r"[★츠]+", " ", text).strip(" ,")
    return text[:limit] if text else "하이라이트"


def hook_lines(c: ShortCandidate) -> list[str]:
    """상단 자막: shorts.suggest_hook 이 만든 [인용 대사, 아이템 맥락]. 없으면 배너 OCR 정리본."""
    if getattr(c, "hook_lines", None):
        return list(c.hook_lines)[:2]
    return [_clean(c.overlay_text)]


CX_BY_STATE = {"inventory": 0.72, "left_panel": 0.28}  # ui_state → 크롭 중심 x (화면 폭 비율)


def crop_track(
    c: ShortCandidate,
    ui: list[dict] | None,
    W: int,
    side: int,
    cx_default: float = 0.5,
    step: float = 0.1,
    ease: float = 0.0,
) -> list[tuple[float, int]]:
    """클립 내 시각(초, 클립 기준) → crop x0. ui_state 구간을 따라 목표를 정한다.
    ease=0 (기본): 상태가 바뀌는 순간 바로 점프 (편집 컷처럼). ease>0: 그 초에 걸쳐 선형 이동 (패닝)."""

    def target(t_abs: float) -> float:
        for u in ui or []:
            if u["start"] <= t_abs < u["end"] and u["label"] in CX_BY_STATE:
                return CX_BY_STATE[u["label"]]
        return cx_default

    n = int((c.end - c.start) / step) + 1
    xs, cur = [], target(c.start)
    for i in range(n):
        t = i * step
        goal = target(c.start + t)
        if ease <= 0 or abs(goal - cur) < 1e-3:
            cur = goal
        else:
            cur += (goal - cur) / max(ease / step, 1)
            cur = goal if abs(goal - cur) < 1e-3 else cur
        x0 = int(max(0, min(W - side, cur * W - side / 2)))
        xs.append((round(t, 2), x0))
    return xs


def build_cmd(
    src: Path,
    c: ShortCandidate,
    meta: dict,
    out_name: str,
    top_png: str,
    cx: float = 0.5,
    nvenc: bool = True,
    cmd_file: str | None = None,
    x0_init: int | None = None,
    sub_file: str | None = None,
    top_h: int = TOP_H,
    bottom: str = "chat",
) -> list[str]:
    """상단 = top_png (1080×top_h, topband.py), 중단 = 게임 정사각 1080,
    하단 = 채팅 ROI (bottom="chat") 또는 검은 띠 (bottom="black", 상단이 채팅 피드일 때 중복을 피하고 대사 자막 자리로)."""
    W, H = meta["width"], meta["height"]
    chat_h = 1920 - top_h - GAME_H
    side = H  # 정사각 크롭 변 = 원본 높이
    x0 = x0_init if x0_init is not None else int(max(0, min(W - side, cx * W - side / 2)))
    chat = meta["rois"].get("chat") if bottom == "chat" else None
    dur = c.end - c.start
    pre = f"[0:v]sendcmd=f={cmd_file}" if cmd_file else "[0:v]null"
    if bottom == "chat":
        src_v = pre + ",split=2[g][c]"
    else:
        src_v = pre + "[g]"
    fc = [src_v, f"[g]crop@game={side}:{side}:{x0}:0,scale={GAME_H}:{GAME_H}[game]"]
    if bottom != "chat":
        fc.append(f"color=c=black:s=1080x{chat_h}:d={dur:.2f}[chat]")
    elif chat:
        cw, ch = chat[2], chat[3]
        sh = int(1080 * ch / cw)  # 폭 1080 으로 맞춘 뒤 높이 chat_h 로 자름/패드
        fc.append(
            f"[c]crop={cw}:{ch}:{chat[0]}:{chat[1]},scale=1080:{sh},"
            f"{f'crop=1080:{chat_h}:0:0' if sh >= chat_h else f'pad=1080:{chat_h}:0:0:black'}[chat]"
        )
    else:
        fc.append(
            f"[c]crop={side}:{int(side * chat_h / 1080)}:{x0}:{H - int(side * chat_h / 1080)},scale=1080:{chat_h}[chat]"
        )
    fc.append(f"[1:v]scale=1080:{top_h},format=yuv420p[top]")
    if sub_file:
        fc.append("[top][game][chat]vstack=inputs=3[v0]")
        fc.append(f"[v0]subtitles={sub_file}[v]")  # 대사 자막 (ASS, libass). 경로는 cwd 기준 상대경로
    else:
        fc.append("[top][game][chat]vstack=inputs=3[v]")
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if nvenc:
        cmd += ["-hwaccel", "cuda"]
    cmd += [
        "-ss",
        f"{c.start:.2f}",
        "-t",
        f"{dur:.2f}",
        "-i",
        str(src.resolve()),
        "-loop",
        "1",
        "-framerate",
        "1",
        "-i",
        top_png,
        "-filter_complex",
        ";".join(fc),
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "h264_nvenc" if nvenc else "libx264",
        "-preset",
        "p4" if nvenc else "veryfast",
    ]
    cmd += ["-cq", "23"] if nvenc else ["-crf", "23"]
    cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", out_name]
    return cmd


def pick_top_mode(c: ShortCandidate, mode: str = "auto") -> str:
    if mode in ("title", "chat"):
        return mode
    kinds = set(c.evidence.get("anchor_kinds", []))
    return "chat" if kinds & {"zoom", "chat"} else "title"


def chat_messages_for(c: ShortCandidate, chat: list[dict] | None, pre: float = 15.0, post: float = 5.0) -> list[dict]:
    if not chat:
        return []

    def ok(m):
        return bool(m.get("nick")) and len(m.get("text", "").strip()) >= 2

    sel = [m for m in chat if ok(m) and c.anchor - pre <= m["t"] <= min(c.end, c.anchor + post)]
    if len(sel) < 2:
        sel = [m for m in chat if ok(m) and c.start <= m["t"] <= c.end]
    out, seen = [], set()
    for m in sel:
        key = (m["nick"] + m["text"]).replace(" ", "")
        if key not in seen:
            seen.add(key)
            out.append({"nick": m["nick"], "text": clean_chat(m["text"])})
    return out


def render_shorts(
    cands: list[ShortCandidate],
    meta: dict,
    out_dir: Path,
    k: int | None = None,
    cx: float = 0.5,
    ui: list[dict] | None = None,
    ease: float = 0.0,
    transcript: dict | None = None,
    subs: bool = True,
    chat: list[dict] | None = None,
    top_mode: str = "title",
    layout: str = "card",
    brand: str = "",
    episode_label: str = "",
    progress=None,
) -> list[dict]:
    """ui = ui_state 구간 목록 — 크롭 중심이 인벤토리/캐릭터창을 따라간다.
    chat = chat_text 메시지 목록 [{t, nick, text}] — 상단 채팅 피드 모드의 입력. top_mode = auto|title|chat.
    기본 layout=card + top_mode=title = 스트리머가 2026-10-18 최종 확정한 포맷(손글씨 제목 띠 + 템 창 추적 크롭 + 대사 자막 + 방송 채팅)."""
    from .topband import CHAT_H_TOP, TITLE_H, chat_band, title_band

    out_dir.mkdir(parents=True, exist_ok=True)
    if layout == "feed":
        return render_feed(
            cands,
            meta,
            out_dir,
            k=k,
            transcript=transcript,
            chat=chat,
            brand=brand,
            episode_label=episode_label,
            progress=progress,
        )
    src = Path(meta["source"])
    index = []
    for rank, c in enumerate(cands, 1):
        if k and rank > k:
            continue
        name = f"{rank:02d}_{c.variant}_{fmt_time(c.start).replace(':', '-')}_{c.score:.2f}.mp4"
        lines = hook_lines(c)
        mode = pick_top_mode(c, top_mode)
        top_png = name.replace(".mp4", "_top.png")
        if mode == "chat":
            msgs = chat_messages_for(c, chat)
            if msgs:
                top_h = CHAT_H_TOP
                chat_band(msgs, out_dir / top_png)
            else:
                mode, top_h = "title", TITLE_H
                title_band(lines, out_dir / top_png)
        else:
            top_h = TITLE_H
            title_band(lines, out_dir / top_png)
        chat_h = 1920 - top_h - GAME_H
        bottom = "black" if mode == "chat" else "chat"
        # 크롭 중심 트랙 → sendcmd 파일 (클립 기준 시각)
        track = crop_track(c, ui, meta["width"], meta["height"], cx, ease=ease)
        cmd_file = name.replace(".mp4", ".cmd")
        moves = sum(1 for a, b in itertools.pairwise(track) if a[1] != b[1])
        (out_dir / cmd_file).write_text("".join(f"{t:.2f} crop@game x {x};\n" for t, x in track), encoding="utf-8")
        sub_file = None
        n_cues = 0
        if subs and transcript:
            from .subtitles import cues_for_clip, write_ass, write_srt

            cues = cues_for_clip(transcript, c.start, c.end)
            if cues:
                sub_file = name.replace(".mp4", ".ass")
                # 게임 영역 하단 HUD(구슬·벨트, 약 180px) 위에 놓는다
                # 하단이 검은 띠면 그 안에(아래 여백 60), 채팅 띠면 게임 HUD 위에
                write_ass(cues, out_dir / sub_file, c.start, margin_v=(60 if bottom == "black" else chat_h + 180))
                write_srt(cues, out_dir / name.replace(".mp4", ".srt"), c.start)
                n_cues = len(cues)
        cmd = build_cmd(
            src,
            c,
            meta,
            name,
            top_png,
            cx,
            cmd_file=cmd_file,
            x0_init=track[0][1],
            sub_file=sub_file,
            top_h=top_h,
            bottom=bottom,
        )
        try:
            subprocess.run(cmd, check=True, cwd=out_dir, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            print(f"  ! nvenc failed ({e.stderr.decode(errors='ignore')[-200:].strip()}), retry libx264")
            subprocess.run(
                build_cmd(
                    src,
                    c,
                    meta,
                    name,
                    top_png,
                    cx,
                    nvenc=False,
                    cmd_file=cmd_file,
                    x0_init=track[0][1],
                    sub_file=sub_file,
                    top_h=top_h,
                    bottom=bottom,
                ),
                check=True,
                cwd=out_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        (out_dir / cmd_file).unlink(missing_ok=True)
        (out_dir / top_png).unlink(missing_ok=True)
        print(f"  {name}  (top={mode} {top_h}px, crop moves: {moves}, subtitle cues: {n_cues})")
        index.append(
            {
                "file": name,
                "variant": c.variant,
                "rank": rank,
                "start": c.start,
                "end": c.end,
                "anchor": c.anchor,
                "score": c.score,
                "axes": c.axes,
                "evidence": c.evidence,
                "hook_mode": c.hook_mode,
                "overlay_text": c.overlay_text,
                "hook_lines": lines,
                "crop_moves": moves,
                "subtitle_cues": n_cues,
                "top_mode": mode,
                "top_h": top_h,
            }
        )
    write_json(out_dir / "index.json", "index", index)
    (out_dir / "index.md").write_text(index_md(index, meta), encoding="utf-8")
    return index


def index_md(index: list[dict], meta: dict) -> str:
    lines = [
        f"# 쇼츠 초안 — {Path(meta['source']).name}",
        "",
        "| # | 파일 | 구간 | 앵커 | 점수 | 근거 | 상단 | 자막 제안 | 판정(keep/no) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in index:
        ev = r["evidence"]
        why = "+".join(ev.get("anchor_kinds", [])) + (f", 컷{ev.get('n_cuts', 0)}" if ev.get("n_cuts") else "")
        lines.append(
            f"| {r['rank']} ({r['variant']}) | `{r['file']}` | {fmt_time(r['start'])}–{fmt_time(r['end'])} "
            f"| {fmt_time(r['anchor'])} | {r['score']:.2f} | {why} | {r.get('top_mode', 'title')} | {' / '.join(r['hook_lines'])} |  |"
        )
    lines += [
        "",
        "- 각 mp4 옆의 `.srt` 는 같은 대사 자막(Premiere 캡션으로 임포트 가능), `.ass` 는 초안에 구운 스타일 원본.",
        "- 판정 열에 keep/no 를 적거나, 쓸 파일을 `keep/` 폴더로 옮기면 `harvest --shorts` 가 정답으로 회수한다 (7단계).",
        "- 훅 모드 `payoff_flash` = 앞 1~2초에 페이오프 장면을 먼저 보여준 뒤 되감기 권장. `cold_open` = 그대로 시작.",
    ]
    return "\n".join(lines)


def render_feed(
    cands: list[ShortCandidate],
    meta: dict,
    out_dir: Path,
    k: int | None = None,
    transcript: dict | None = None,
    chat: list[dict] | None = None,
    brand: str = "",
    episode_label: str = "",
    progress=None,
) -> list[dict]:
    """레이아웃 feed: 16:9 영상 전체 + 발화 자막 + 채팅 하이라이트 + 회차 띠 + 훅 + 채팅 피드 + 인트로. layout_feed.py"""
    from . import layout_feed as LF

    src = Path(meta["source"])
    brand = brand or "디아블로2 하이라이트"
    episode_label = episode_label or Path(meta["source"]).stem
    index = []
    total = min(len(cands), k) if k else len(cands)
    for rank, c in enumerate(cands, 1):
        if k and rank > k:
            continue
        name = f"{rank:02d}_{c.variant}_{fmt_time(c.start).replace(':', '-')}_{c.score:.2f}.mp4"
        if progress:
            progress((rank - 1) / max(total, 1), f"{rank}/{total} {name}")
        lines = hook_lines(c)
        hook = lines[-1] if len(lines) > 1 else lines[0]  # 고정 훅 = 아이템 맥락 줄 ("지존참 직득!")
        intro = [episode_label, hook] if episode_label and hook else lines[:2]  # 인트로: 회차(흰) / 득템 훅(금)
        static_png = name.replace(".mp4", "_static.png")
        ass_file = name.replace(".mp4", ".ass")
        LF.build_static(c, brand, episode_label, hook, out_dir / static_png)
        (out_dir / ass_file).write_text(LF.build_ass(c, transcript, chat, intro), encoding="utf-8")
        n_cues = 0
        if transcript:
            from .subtitles import cues_for_clip, write_srt

            cues = cues_for_clip(transcript, c.start, c.end, max_chars=26)
            n_cues = len(cues)
            write_srt(cues, out_dir / name.replace(".mp4", ".srt"), c.start)
        cmd = LF.build_cmd(src, c, meta, name, static_png, ass_file)
        try:
            subprocess.run(cmd, check=True, cwd=out_dir, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            print(f"  ! nvenc failed ({e.stderr.decode(errors='ignore')[-300:].strip()}), retry libx264")
            subprocess.run(
                LF.build_cmd(src, c, meta, name, static_png, ass_file, nvenc=False),
                check=True,
                cwd=out_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        (out_dir / static_png).unlink(missing_ok=True)
        print(f"  {name}  (layout=feed, intro {LF.INTRO_SEC}s)")
        index.append(
            {
                "file": name,
                "variant": c.variant,
                "rank": rank,
                "start": c.start,
                "end": c.end,
                "anchor": c.anchor,
                "score": c.score,
                "axes": c.axes,
                "evidence": c.evidence,
                "hook_mode": c.hook_mode,
                "overlay_text": c.overlay_text,
                "hook_lines": lines,
                "layout": "feed",
                "top_mode": "feed",
                "top_h": 0,
                "subtitle_cues": n_cues,
            }
        )
    write_json(out_dir / "index.json", "index", index)
    (out_dir / "index.md").write_text(index_md(index, meta), encoding="utf-8")
    return index
