"""판정 학습: 판정이 적거나 한쪽뿐이면 기본값, 경향이 뚜렷하면 그 축 쪽으로 (판정 수만큼만) 옮겨 간다."""

import csv
import json

import pytest

from clipforge.preference import (
    AXES,
    AXIS_WEIGHTS,
    MIN_SAMPLES,
    Judgment,
    collect_judgments,
    current_preference,
    fit_preference,
)


def _j(keep: bool, **axes) -> Judgment:
    base = {k: 0.5 for k in AXES}
    base.update(axes)
    return Judgment("ep", 0.0, 30.0, keep, base)


def test_too_few_judgments_keep_default():
    pref = fit_preference([_j(True), _j(False)] * ((MIN_SAMPLES - 1) // 2))
    assert not pref.learned and pref.weights == AXIS_WEIGHTS and "부터 반영" in pref.reason


def test_one_sided_judgments_keep_default():
    pref = fit_preference([_j(True, chat=0.9)] * 12)
    assert not pref.learned and pref.weights == AXIS_WEIGHTS and pref.n_keep == 12 and pref.n_no == 0


def test_clear_preference_moves_weight_toward_that_axis():
    # 채팅 반응이 큰 초안만 쓸 만하다고 하고, 득템만 있고 채팅이 조용한 초안은 안 씀
    keeps = [_j(True, chat=0.9 + 0.01 * i, payoff=0.2) for i in range(8)]
    nos = [_j(False, chat=0.05, payoff=1.0) for _ in range(8)]
    pref = fit_preference(keeps + nos)
    assert pref.learned and 0 < pref.blend < 1
    assert pref.weights["chat"] > AXIS_WEIGHTS["chat"]
    assert pref.weights["payoff"] < AXIS_WEIGHTS["payoff"]
    assert sum(pref.weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(v >= 0 for v in pref.weights.values())


def test_more_judgments_move_further():
    def make(n):
        return [_j(True, chat=0.9, payoff=0.2) for _ in range(n)] + [_j(False, chat=0.05, payoff=1.0) for _ in range(n)]

    few, many = fit_preference(make(4)), fit_preference(make(40))
    assert many.blend > few.blend
    assert many.weights["chat"] > few.weights["chat"]


def test_collect_matches_judgments_to_candidates_and_saves(tmp_path):
    labels, cache = tmp_path / "labels", tmp_path / "cache"
    (cache / "ep1").mkdir(parents=True)
    labels.mkdir()
    cands = [
        {
            "start": 10.0,
            "end": 40.0,
            "axes": {"payoff": 1.0, "reaction": 0.7, "chat": 0.9, "completeness": 1.0, "hook": 1.0},
        },
        {
            "start": 100.0,
            "end": 130.0,
            "axes": {"payoff": 0.0, "reaction": 0.2, "chat": 0.1, "completeness": 0.5, "hook": 0.5},
        },
    ]
    (cache / "ep1" / "shorts.json").write_text(json.dumps({"schema_version": 1, "candidates": cands}), encoding="utf-8")
    with open(labels / "ep1.shorts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["start", "end", "label", "note"])
        w.writeheader()
        w.writerow({"start": "10.0", "end": "40.0", "label": "keep", "note": "ui"})
        w.writerow({"start": "101.0", "end": "129.0", "label": "no", "note": "ui | 재미없음"})
        w.writerow({"start": "300.0", "end": "320.0", "label": "keep", "note": "짝이 없는 판정"})
        w.writerow({"start": "10.0", "end": "40.0", "label": "title_item", "note": "약한 정답은 판정이 아님"})
    js = collect_judgments(labels, cache)
    assert [(j.keep, j.axes["chat"]) for j in js] == [(True, 0.9), (False, 0.1)]

    out = tmp_path / "reports" / "preference.json"
    pref = current_preference(labels, cache, save_to=out)
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["n_keep"] == 1 and saved["n_no"] == 1 and saved["weights"] == pref.weights


def test_decision_keeps_axes_so_rerunning_shorts_does_not_lose_judgments(tmp_project):
    from clipforge.api.methods import Engine

    engine = Engine(tmp_project)
    vid = "epA"
    (tmp_project.cache / vid).mkdir(parents=True)
    shorts = tmp_project.cache / vid / "shorts.json"
    axes = {"payoff": 1.0, "reaction": 0.8, "chat": 0.6, "completeness": 1.0, "hook": 1.0}
    shorts.write_text(json.dumps({"schema_version": 1, "candidates": [{"start": 12.0, "end": 44.0, "axes": axes}]}))

    engine.decision_set(vid, 12.0, 44.0, "keep")
    # 후보를 다시 만들어 구간이 완전히 바뀌어도
    shorts.write_text(json.dumps({"schema_version": 1, "candidates": [{"start": 300.0, "end": 330.0, "axes": axes}]}))
    js = collect_judgments(tmp_project.labels, tmp_project.cache)
    assert len(js) == 1 and js[0].keep and js[0].axes["chat"] == 0.6

    engine.decision_set(vid, 12.0, 44.0, "")  # 판정 취소하면 축 점수도 지운다
    assert collect_judgments(tmp_project.labels, tmp_project.cache) == []
