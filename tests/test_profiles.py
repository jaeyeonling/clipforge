"""공통 설정 + 게임 프로필 덮어쓰기, 파일 이름으로 게임 추정."""

from pathlib import Path

from clipforge.profiles import SHARED_KEYS, guess_game, load_settings


def _games(tmp_path: Path) -> Path:
    gd = tmp_path / "games"
    gd.mkdir()
    (gd / "common.yaml").write_text(
        """
speech_keywords:
  강: {weight: 1.0, words: [미쳤다, 대박]}
  중: {weight: 0.7, words: [와]}
speech_kernel: {pre: 20, post: 6, cooldown: 8}
pipelines:
  edited: {signals: all, scene_cuts: true}
label_categories: [{key: drop}, {key: reaction}]
""",
        encoding="utf-8",
    )
    (gd / "dnf.yaml").write_text(
        """
name: dnf
speech_keywords:
  강: {weight: 1.0, words: [태초, 에픽]}
speech_kernel: {cooldown: 4}
label_categories: [{key: raid_clear}]
rois: {result: [0.1, 0.1, 0.5, 0.5]}
""",
        encoding="utf-8",
    )
    (gd / "d2r.yaml").write_text("name: d2r\n", encoding="utf-8")
    return gd


def test_without_game_returns_common(tmp_path):
    s = load_settings(None, _games(tmp_path))
    assert s["speech_kernel"]["cooldown"] == 8 and s["label_categories"][0]["key"] == "drop"


def test_game_overrides_shared_keys_dicts_merge_lists_replace(tmp_path):
    s = load_settings("dnf", _games(tmp_path))
    assert s["speech_keywords"]["강"]["words"] == ["태초", "에픽"]  # 같은 그룹은 게임 값
    assert s["speech_keywords"]["중"]["words"] == ["와"]  # 게임이 안 정한 그룹은 공통 값
    assert s["speech_kernel"] == {"pre": 20, "post": 6, "cooldown": 4}  # 사전은 한 단계씩 합침
    assert s["label_categories"] == [{"key": "raid_clear"}]  # 목록은 통째로
    assert s["pipelines"]["edited"]["signals"] == "all"
    assert "rois" not in s  # 공통 키만 섞는다 (화면 영역은 load_profile 의 몫)
    assert set(SHARED_KEYS) >= {"speech_keywords", "pipelines", "label_categories"}


def test_unknown_game_falls_back_to_common(tmp_path):
    gd = _games(tmp_path)
    assert load_settings("nope", gd) == load_settings(None, gd)


def test_guess_game_uses_any_profile_name(tmp_path):
    gd = _games(tmp_path)
    assert guess_game(Path("dnf_raid_0412.mp4"), games_dir=gd) == "dnf"
    assert guess_game(Path("D2R-ladder-59.mp4"), games_dir=gd) == "d2r"
    assert guess_game(Path("common_x.mp4"), games_dir=gd) == "d2r"  # common 은 게임이 아니다
    assert guess_game(Path("ep59.mp4"), default="d2r", games_dir=gd) == "d2r"


def test_saved_regions_go_to_data_folder_and_survive_app_updates(tmp_project):
    """화면 영역 탭에서 저장한 값은 데이터 폴더에. 앱의 games/ (업데이트가 교체하는 곳)는 그대로."""
    from clipforge import calibrate
    from clipforge.profiles import GAMES, load_profile

    app_file = GAMES / "d2r.yaml"
    before = app_file.read_bytes()
    base = load_profile("d2r", tmp_project.data_root / "profiles")
    new_chat = [0.01, 0.8, 0.25, 0.19]
    calibrate.set_rois(tmp_project, "d2r", {**base["rois"], "chat": new_chat})

    assert app_file.read_bytes() == before
    assert (tmp_project.data_root / "profiles" / "d2r.yaml").exists()
    merged = load_profile("d2r", tmp_project.data_root / "profiles")
    assert merged["rois"]["chat"] == new_chat
    assert merged["rois"]["banner"] == base["rois"]["banner"]
    assert calibrate.get_rois(tmp_project, "d2r")["rois"]["chat"] == new_chat
