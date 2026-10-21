# 다른 게임 추가하기

clipforge 는 게임마다 다른 것(화면 배치 · 어휘 · 쓸 신호)을 **데이터 파일**로 분리해 두었어요. 새 게임은 `games/<게임>.yaml` 하나를 더하는 것에서 시작해요. 코드는 그 게임에만 있는 화면 단서를 읽어야 할 때만 고쳐요.

## 무엇이 그대로 되고, 무엇을 더해야 하나

| 신호 | 새 게임에서 | 필요한 것 |
|---|---|---|
| `audio_loudness` · `frame_motion` · `cut_density` | 그대로 돼요 | 없음 |
| `speech_keyword` | 그대로 돼요 | 그 게임 방송의 리액션·득템 어휘 (`speech_keywords`) |
| `chat_burst` · `chat_text` | 화면에 채팅 오버레이가 있으면 돼요 | 채팅 영역 `rois.chat` |
| `item_banner` | 방송 화면에 "득템 :" 같은 누적 텍스트가 있으면 돼요 | 배너 영역 `rois.banner` |
| `edit_emphasis` | HUD 가 사라지는 구간을 줌·카드로 봐요 | 체력·마나 같은 HUD 영역 `rois.hud_red_orb` · `rois.hud_blue_orb` |
| `ui_state` (세로 크롭 추적) | 디아블로2 패널 제목("소지품", "캐릭터")을 읽어요 | 그 게임의 패널 단서를 읽는 신호를 따로 써야 해요 |
| 라이브 아이템 감지 | 디아블로2 바닥 라벨 색을 읽어요 | 그 게임용 감지기 (`clipforge/live/detect.py` 참고) |

쓸 수 없는 신호는 `pipelines` 에서 빼면 돼요(아래). 빠진 신호는 점수에서 0 으로 다뤄져요.

## 1. 프로필 파일 만들기

`games/d2r.yaml` 을 복사해 `games/<게임>.yaml` 로 저장하고 고쳐요. 이름은 영문 소문자로 짧게(`dnf`, `poe` …). 영상 파일 이름이 `<게임>_` 이나 `<게임>-` 로 시작하면 그 게임으로 알아서 골라요. 등록 화면에서 직접 고를 수도 있어요(게임이 둘 이상이면 선택칸이 나와요).

```yaml
name: dnf
title: 던전앤파이터            # 등록 화면에 보일 이름
schema_version: 1
resolution_ref: [1920, 1080]   # 화면 영역을 잰 기준 해상도. 실제 해상도에 맞춰 비율로 변환돼요

rois:                          # [x, y, w, h], 화면 전체를 1로 본 비율
  banner: [0.0, 0.0, 0.40, 0.12]
  chat:   [0.0, 0.80, 0.25, 0.20]
roi_crops: [banner, chat]      # OCR 할 영역은 원본 해상도로 잘라 저장

frames:
  fps: 1.0
  max_height: 1080
  scene_cuts: true             # 편집본의 장면 전환 (원본 녹화는 false)

events:                        # 이벤트 → 곡선 커널(초): 사건 시각 t 를 [t-pre, t+post] 로 펼쳐요
  item_banner: {labels: [append], pre: 8, post: 6, weight: 1.5}
```

## 2. 화면 영역 맞추기

영역은 손으로 재지 않아도 돼요.

1. 그 게임의 편집본 하나를 등록하고 **만들기**를 한 번 돌려요(영상 읽기까지만 돼도 충분해요).
2. 설정에서 고급 기능을 켜고 **화면 영역** 탭 → **점검**. 영역마다 글자가 실제로 읽히는 비율이 나와요.
3. **영역 위치 고치기**를 열면 실제 프레임 위에 박스가 그려져요. 끌어서 옮기고 모서리로 크기를 바꾼 뒤 **프로필 저장**하면 데이터 폴더의 `profiles/<게임>.yaml` 에 사용자 값으로 저장돼요. 앱 업데이트가 덮어쓰지 않아요. 다른 사람과 같은 값을 쓰려면 그 값을 `games/<게임>.yaml` 의 `rois` 로 옮기세요.
4. 배너·채팅 영역을 바꿨으면 고급 설정의 **처음부터 다시**로 한 번 다시 돌려요.

## 3. 어휘와 신호 묶음

공통 설정 `games/common.yaml` 은 모든 게임이 같이 써요. 게임 프로필에 같은 키를 쓰면 **그 게임에서는 프로필 값이 이겨요.** 덮어쓸 수 있는 키는 `speech_keywords` · `chat_keywords` · `speech_kernel` · `transcribe` · `pipelines` · `label_categories` 예요. 사전은 한 단계씩 합치고, 목록은 통째로 바꿔요.

```yaml
# games/dnf.yaml 에 이어서
speech_keywords:
  득템: {weight: 1.0, words: [태초, 에픽, 레전더리, 증폭 성공]}   # '강'·'중'·'약' 그룹은 공통 값을 그대로 써요
pipelines:
  edited:
    signals: [audio_loudness, frame_motion, cut_density, speech_keyword, chat_burst, chat_text, item_banner]
    scene_cuts: true
label_categories:
  - {key: clear,    label: 클리어,  hint: 던전·레이드 결과창, color: "#f0f660", shortcut: "1"}
  - {key: reaction, label: 리액션,  hint: 환호·탄식,          color: "#9be28a", shortcut: "2"}
```

## 4. 확인하기

- `python -m pytest` 로 기존 동작이 그대로인지 봐요. 프로필 합치기 규칙은 `tests/test_profiles.py` 가 지켜요.
- 그 게임 편집본 하나로 쇼츠 초안을 만들고 쓸 만함 / 안 씀을 눌러 보세요. 기록 탭에서 1위 적중과 순위 점수(MRR)가 보여요. 판정이 6개 이상 쌓이면 점수 축의 비중이 그 게임 판정에 맞춰져요.
- 새 신호가 필요하면 `clipforge/signals/` 에 플러그인을 더해요. 방법은 [DEVELOPMENT.md](DEVELOPMENT.md#신호-추가하기).
- 아이템 이름 사전이 있으면 `data/<게임>/` 에 두고, 디아블로2의 `scripts/build_items.py` · `clipforge/lexicon.py` 를 참고해 연결해요.
