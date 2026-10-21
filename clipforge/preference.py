"""판정 학습: 쓸 만함 / 안 씀 판정으로 쇼츠 점수 축의 가중치를 다시 맞춘다.

쇼츠 후보는 다섯 축(payoff · reaction · chat · completeness · hook)의 가중합으로 순위가 매겨진다.
사람이 초안마다 keep / no 를 누르면 labels/<id>.shorts.csv 에 쌓이는데, 그 판정을 그 후보의 축 점수와 짝지어
"어떤 축이 높을 때 쓸 만하다고 했는가"를 배운다.

판정은 적고(회차당 몇 개) 한쪽으로 쏠리기 쉬워서, 학습은 보수적으로 한다.
  1. 판정이 MIN_SAMPLES 개 미만이거나 keep · no 중 하나만 있으면 기본 가중치를 그대로 쓴다.
  2. 기본 가중치를 사전 분포로 둔 L2 로지스틱 회귀(MAP)로 축 계수를 맞춘다.
  3. 음수 계수는 0으로 자르고 합이 1이 되게 정규화한 뒤, 판정 수에 비례해서만 기본값에서 옮겨 간다:
     w = a * 학습값 + (1 - a) * 기본값,  a = n / (n + SHRINK).
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

AXES = ("payoff", "reaction", "chat", "completeness", "hook")
AXIS_WEIGHTS: dict[str, float] = {"payoff": 0.35, "reaction": 0.25, "chat": 0.15, "completeness": 0.15, "hook": 0.10}
MIN_SAMPLES = 6  # 이보다 적으면 배우지 않는다
SHRINK = 20.0  # 판정 20개에서 학습값과 기본값을 반반 섞는다
PRIOR_SCALE = 4.0  # 기본 가중치를 로지스틱 계수로 옮길 때의 배율 (사전 분포의 중심)
L2 = 1.0  # 사전 분포 쪽으로 당기는 세기


@dataclass
class Judgment:
    episode: str
    start: float
    end: float
    keep: bool
    axes: dict[str, float]


@dataclass
class Preference:
    weights: dict[str, float]
    default: dict[str, float] = field(default_factory=lambda: dict(AXIS_WEIGHTS))
    n_keep: int = 0
    n_no: int = 0
    learned: bool = False
    blend: float = 0.0  # 학습값이 섞인 비율 (0 = 기본값 그대로)
    reason: str = ""
    updated: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


def axes_path(labels_dir: Path, vid: str) -> Path:
    """판정할 때 남긴 축 점수: {"<start>-<end>": {payoff, reaction, …}}."""
    return labels_dir / f"{vid}.shorts.axes.json"


def load_axes(path: Path) -> dict[str, dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def collect_judgments(labels_dir: Path, cache_dir: Path) -> list[Judgment]:
    """모든 회차의 keep / no 판정을 축 점수와 짝짓는다.
    판정할 때 남긴 축 점수가 있으면 그걸 쓰고, 없으면(예전 판정·폴더 회수) 지금 shorts.json 에서 절반 이상 겹치는 후보를 찾는다.
    짝이 없는 판정은 버린다."""
    out: list[Judgment] = []
    for lab in sorted(labels_dir.glob("*.shorts.csv")):
        vid = lab.name[: -len(".shorts.csv")]
        saved = load_axes(axes_path(labels_dir, vid))
        sp = cache_dir / vid / "shorts.json"
        cands: list[dict] = []
        if sp.exists():
            data = json.loads(sp.read_text(encoding="utf-8"))
            cands = data.get("candidates", data) if isinstance(data, dict) else data
        with open(lab, encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r.get("label") in ("keep", "no")]
        for r in rows:
            try:
                s, e = float(r["start"]), float(r["end"])
            except (KeyError, ValueError):
                continue
            axes = saved.get(f"{s:.1f}-{e:.1f}")
            if axes is None:
                best, best_iou = None, 0.5  # 구간이 절반 이상 겹치는 후보만 같은 초안으로 본다
                for c in cands:
                    iou = _overlap(s, e, float(c["start"]), float(c["end"]))
                    if iou > best_iou and c.get("axes"):
                        best, best_iou = c, iou
                axes = best["axes"] if best is not None else None
            if axes is not None:
                out.append(Judgment(vid, s, e, r["label"] == "keep", {k: float(axes.get(k, 0.0)) for k in AXES}))
    return out


def _fit_logistic(x: np.ndarray, y: np.ndarray, prior: np.ndarray, l2: float = L2, steps: int = 3000) -> np.ndarray:
    """사전 분포(prior) 쪽으로 당기는 L2 로지스틱 회귀. 계수 [bias, w1..w5] 를 돌려준다."""
    xb = np.hstack([np.ones((len(x), 1)), x])
    beta = np.concatenate([[0.0], prior])
    center = beta.copy()
    lr = 0.5
    for _ in range(steps):
        p = 1.0 / (1.0 + np.exp(-(xb @ beta)))
        grad = xb.T @ (p - y) / len(y)
        grad[1:] += l2 * (beta[1:] - center[1:]) / len(y)
        beta -= lr * grad
    return beta


def fit_preference(judgments: list[Judgment], default: dict[str, float] | None = None) -> Preference:
    default = dict(default or AXIS_WEIGHTS)
    n_keep = sum(1 for j in judgments if j.keep)
    n_no = len(judgments) - n_keep
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    if len(judgments) < MIN_SAMPLES:
        return Preference(
            default,
            default,
            n_keep,
            n_no,
            False,
            0.0,
            f"판정 {len(judgments)}개예요. {MIN_SAMPLES}개부터 반영해요",
            stamp,
        )
    if n_keep == 0 or n_no == 0:
        return Preference(default, default, n_keep, n_no, False, 0.0, "쓸 만함과 안 씀이 둘 다 있어야 반영해요", stamp)

    x = np.array([[j.axes[k] for k in AXES] for j in judgments], dtype=float)
    y = np.array([1.0 if j.keep else 0.0 for j in judgments])
    prior = np.array([default[k] for k in AXES]) * PRIOR_SCALE
    beta = _fit_logistic(x, y, prior)
    coef = np.clip(beta[1:], 0.0, None)
    if coef.sum() <= 1e-9:
        return Preference(default, default, n_keep, n_no, False, 0.0, "판정에서 일관된 경향을 찾지 못했어요", stamp)
    learned = coef / coef.sum()
    a = len(judgments) / (len(judgments) + SHRINK)
    w = a * learned + (1 - a) * np.array([default[k] for k in AXES])
    weights = {k: round(float(v), 4) for k, v in zip(AXES, w / w.sum(), strict=True)}
    return Preference(weights, default, n_keep, n_no, True, round(a, 3), f"판정 {len(judgments)}개를 반영했어요", stamp)


def current_preference(labels_dir: Path, cache_dir: Path, save_to: Path | None = None) -> Preference:
    """지금까지의 판정으로 가중치를 맞추고, save_to 가 있으면 화면이 읽을 수 있게 저장한다."""
    pref = fit_preference(collect_judgments(labels_dir, cache_dir))
    if save_to is not None:
        save_to.parent.mkdir(parents=True, exist_ok=True)
        save_to.write_text(json.dumps(pref.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return pref
