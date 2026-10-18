"""쇼츠 초안 렌더 (L4, Phase 1).

shorts.json 의 후보를 1080×1920 세로 초안 mp4 로 뽑는다. Premiere 전에 "눈으로 보고 고르기" 용도라 화질보다 속도.
레이아웃(한국 클립 채널 A형 단순화, docs/research/shorts_formula.md):
  상단 400px  검은 띠 + 훅 텍스트 2줄 (지금은 배너 OCR 원문/시각. 8단계 사전 뒤 아이템명·가치로 교체)
  중단 1080px 게임 화면 정사각 크롭 (기본 중앙. --cx 로 중심 이동. 툴팁 추적은 후속)
  하단 440px  채팅 오버레이 ROI 확대 (한국 쇼츠의 채팅 스크린샷 관례)
NVDEC 디코딩 → NVENC 인코딩. 실패 시 libx264. 폰트는 맑은 고딕 Bold.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .shorts import ShortCandidate
from .timeline import fmt_time

FONT = "C\\:/Windows/Fonts/malgunbd.ttf"      # ffmpeg 필터 안에서 'C:' 콜론은 백슬래시 하나로 이스케이프 (C\:)
TOP_H, GAME_H, CHAT_H = 400, 1080, 440


def _clean(text: str, limit: int = 22) -> str:
    text = re.sub(r"^(득템|득렘|득램|특템|특램|템|렘)", "", text)
    text = re.sub(r"[★츠]+", " ", text).strip(" ,")
    return text[:limit] if text else "하이라이트"


def hook_lines(c: ShortCandidate) -> list[str]:
    line1 = _clean(c.overlay_text)
    kinds = "+".join(c.evidence.get("anchor_kinds", []))
    line2 = f"{fmt_time(c.anchor)}  {c.variant}  {kinds}"
    return [line1, line2]


def build_cmd(src: Path, c: ShortCandidate, meta: dict, out_name: str, hook_file: str, cx: float = 0.5,
              nvenc: bool = True) -> list[str]:
    W, H = meta["width"], meta["height"]
    side = H                                     # 정사각 크롭 변 = 원본 높이
    x0 = int(max(0, min(W - side, cx * W - side / 2)))
    chat = meta["rois"].get("chat")
    dur = c.end - c.start
    fc = [f"[0:v]split=2[g][c]",
          f"[g]crop={side}:{side}:{x0}:0,scale={GAME_H}:{GAME_H}[game]"]
    if chat:
        cw, ch = chat[2], chat[3]
        sh = int(1080 * ch / cw)                 # 폭 1080 으로 맞춘 뒤 높이 CHAT_H 로 자름/패드
        fc.append(f"[c]crop={cw}:{ch}:{chat[0]}:{chat[1]},scale=1080:{sh},"
                  f"{'crop=1080:%d:0:0' % CHAT_H if sh >= CHAT_H else 'pad=1080:%d:0:0:black' % CHAT_H}[chat]")
    else:
        fc.append(f"[c]crop={side}:{int(side * CHAT_H / 1080)}:{x0}:{H - int(side * CHAT_H / 1080)},scale=1080:{CHAT_H}[chat]")
    fc.append(f"color=c=black:s=1080x{TOP_H}:d={dur:.2f}[top]")
    fc.append(f"[top]drawtext=fontfile='{FONT}':textfile={hook_file}:fontcolor=white:fontsize=60:line_spacing=18:"
              f"borderw=3:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2[topt]")
    fc.append("[topt][game][chat]vstack=inputs=3[v]")
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if nvenc:
        cmd += ["-hwaccel", "cuda"]
    cmd += ["-ss", f"{c.start:.2f}", "-t", f"{dur:.2f}", "-i", str(src.resolve()),
            "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "0:a?",
            "-c:v", "h264_nvenc" if nvenc else "libx264", "-preset", "p4" if nvenc else "veryfast"]
    cmd += ["-cq", "23"] if nvenc else ["-crf", "23"]
    cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", out_name]
    return cmd


def render_shorts(cands: list[ShortCandidate], meta: dict, out_dir: Path, k: int | None = None,
                  cx: float = 0.5) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    src = Path(meta["source"])
    index = []
    by_variant: dict[str, int] = {}
    for c in cands:
        by_variant[c.variant] = by_variant.get(c.variant, 0) + 1
        rank = by_variant[c.variant]
        if k and rank > k:
            continue
        name = f"{c.variant}_{rank:02d}_{fmt_time(c.start).replace(':', '-')}_{c.score:.2f}.mp4"
        hook_file = name.replace(".mp4", ".txt")
        lines = hook_lines(c)
        (out_dir / hook_file).write_text("\n".join(lines), encoding="utf-8")
        cmd = build_cmd(src, c, meta, name, hook_file, cx)
        try:
            subprocess.run(cmd, check=True, cwd=out_dir, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            print(f"  ! nvenc failed ({e.stderr.decode(errors='ignore')[-200:].strip()}), retry libx264")
            subprocess.run(build_cmd(src, c, meta, name, hook_file, cx, nvenc=False), check=True, cwd=out_dir,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (out_dir / hook_file).unlink(missing_ok=True)
        print(f"  {name}")
        index.append({"file": name, "variant": c.variant, "rank": rank, "start": c.start, "end": c.end,
                      "anchor": c.anchor, "score": c.score, "axes": c.axes, "evidence": c.evidence,
                      "hook_mode": c.hook_mode, "overlay_text": c.overlay_text, "hook_lines": lines})
    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "index.md").write_text(index_md(index, meta), encoding="utf-8")
    return index


def index_md(index: list[dict], meta: dict) -> str:
    lines = [f"# 쇼츠 초안 — {Path(meta['source']).name}", "",
             "| # | 파일 | 구간 | 앵커 | 점수 | 근거 | 훅 모드 | 자막 제안 | 판정(keep/no) |", "|---|---|---|---|---|---|---|---|---|"]
    for r in index:
        ev = r["evidence"]
        why = "+".join(ev.get("anchor_kinds", [])) + (f", 컷{ev.get('n_cuts', 0)}" if ev.get("n_cuts") else "")
        lines.append(f"| {r['variant']} {r['rank']} | `{r['file']}` | {fmt_time(r['start'])}–{fmt_time(r['end'])} "
                     f"| {fmt_time(r['anchor'])} | {r['score']:.2f} | {why} | {r['hook_mode']} | {r['hook_lines'][0]} |  |")
    lines += ["", "- 판정 열에 keep/no 를 적거나, 쓸 파일을 `keep/` 폴더로 옮기면 `harvest --shorts` 가 정답으로 회수한다 (7단계).",
              "- 훅 모드 `payoff_flash` = 앞 1~2초에 페이오프 장면을 먼저 보여준 뒤 되감기 권장. `cold_open` = 그대로 시작."]
    return "\n".join(lines)
