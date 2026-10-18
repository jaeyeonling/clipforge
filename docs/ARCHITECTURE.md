# clipforge 아키텍처 설계 (v1 초안, 2026-10-18)

> 참고 레포 6개(AutoEditor, Auto-clipper, auto-highlighter, automated-content-pipeline, vod-to-viral, crispy)와
> 로컬 환경 실측(RTX 4070 SUPER, FFmpeg 9.0.2)을 바탕으로 정리. 각 결정의 근거는 절 끝의 `근거:` 참조.

## 0. 조사에서 확인한 사실

| 항목 | 확인 내용 | 설계 반영 |
|---|---|---|
| 업계 표준 파이프라인 | 전부 동일: ffmpeg 추출 → **1초 단위 시계열** → 정규화 → 임계/피크 → 최소간격 디듀프(15~20s) → 고정 패딩 컷 → 폴더+JSON | 현재 clipforge 뼈대가 이미 이 구조. 유지 |
| 융합 방식 | 모두 하드코딩 선형 가중합(70/30, 35/30/25/10). 학습 융합 없음 | 가중합 유지 + Auto-clipper의 **동의 보너스**, **억제 마스크** 추가 |
| 평가 | 6개 중 e-kemeny 1개만 GT 대비 P/R/F1(영상 1개). 나머지 전무 | **평가 루프가 이 프로젝트의 차별점**. 정답 생성 비용을 줄이는 `align`이 핵심 |
| 게임 UI 신호 | AutoEditor: YOLO 38클래스로 UI 상태 이벤트 → 프레임 집합 연산. crispy: 게임별 고정 crop + 소형 분류기. Auto-clipper: 게임별 HSV 범위를 데이터(dict)로 | 게임 프로필을 **데이터 파일**로 분리. YOLO는 최후 수단, 색 마스크/템플릿/OCR 먼저 |
| D2R 아이템 인식 | d2r-image(2022 중단, tesserocr 의존). 방식은 재사용 가능: HSV 색 마스크(gold/green/orange…) → 어두운 라벨 박스 contour → OCR psm7 → 이름 사전 매칭 | 라이브러리 의존 대신 **방식만 자체 구현**. 색 범위 상수는 차용 |
| Whisper 트리거 | Auto-clipper: 트리거 단어 시각 t → `[t-30, t+5]` 창, 10s cooldown | 이벤트→곡선 어댑터의 기본 커널로 채택 |
| Premiere 출력 | AutoEditor: xmeml v5를 ElementTree로 직접 생성. 컷을 이어붙임 | xmeml 직접 생성. 단 **원본 타임라인 위치 유지 + 마커** (사람 마감용) |
| 하드웨어 | NVDEC 동작 확인. 1080p60 60s: 디코드만 3.7s, 프록시(libx264)+썸네일 5.6~6.3s. **병목은 인코딩**, 디코딩 아님 | 프록시는 기본 생략(lazy). 프레임 추출만 기본 |
| FFmpeg 빌드 | `--enable-whisper`(whisper.cpp 필터), `--enable-chromaprint` 내장 | Python CUDA 의존성 없이 전사·음성 지문 가능. 옵션으로 보유 |

## 1. 목표와 단계 (2026-10-18 결정)

**Phase 1 — 편집본 → 쇼츠.** 친구의 완성 편집본(10~15분, 4K60)에서 쇼츠로 뽑을 30~60초 구간을 골라 Premiere 세로(1080×1920) 시퀀스 + 검토용 mp4 초안으로 낸다.
- 입력이 이미 하이라이트 밀도가 높으므로 문제는 "걸러내기"가 아니라 **"순위 매기기"**. 지표는 recall보다 **hit@K**(상위 K개 후보 중 친구가 실제로 고른 것)가 1순위.
- 정답: 친구가 이미 올린 쇼츠가 있으면 `align`으로 편집본에 역매핑. 없으면 `export → keep/ → harvest` 루프로 친구/우리가 고른 것이 정답.
- 편집본에만 있는 신호를 적극 활용: 득템 배너 갱신, 삽입 설명 카드(친구가 강조한 지점), 컷 밀도(잘게 자른 구간 = 긴장), 채팅 오버레이 변화율, 후원 알림, 발화 키워드.

**Phase 2 — 원본 녹화 → 편집본.** Phase 1에서 신호·평가 루프가 의미 있는 숫자를 내면, 같은 하네스에 2시간 원본을 넣고 친구 편집본을 `align`해 정답을 만들어 recall/coverage로 진행. (0~5절 대부분이 이 단계를 위한 설계이며 그대로 유효)

두 단계는 **같은 코드**를 쓴다. 다른 것은 입력 영상, 정답의 출처, 1순위 지표, 출력 시퀀스 포맷뿐. 게임 프로필·신호 플러그인·판정 층·평가는 공유.

**비목표(당분간)**: 업로드, 자막 생성, BGM, 완전 자동 편집. 세로 리프레이밍은 Premiere 모션 파라미터(스케일/위치)로만 — 얼굴 추적 같은 건 안 함.

## 2. 레이어 구조

```
videos/<id>.mp4 ─▶ L0 prep ─▶ cache/<id>/{meta.json, audio.wav, frames/}
                                 │
                   L1 signals ◀──┤  games/<game>.yaml (ROI, 색범위, 템플릿, 키워드)
                   Curve | Events│
                                 ▼
                   L2 decide ── events→curve 어댑터 → 가중합 + 동의보너스 × 억제마스크 → 임계 → 군집 → candidates.json (+evidence)
                                 │
         ┌── L3 eval ◀───────────┼──────────▶ L4 output ── review/<id>/*.mp4 ─ keep/ ─ harvest
         │   recall/coverage     │                       └─ premiere/<id>.xml (마커 + 세그먼트 트랙)
         │   라벨별 · 놓친 구간   │
         └── labels/<id>.csv ◀── align (친구 최종본 ↔ 원본 자동 정렬) ◀── finals/<id>.mp4
```

### L0 prep — 한 번만 디코딩
- `meta.json`: ffprobe + `game` 필드(파일명 규칙 또는 `--game`).
- `audio.wav`: 16kHz mono. (Whisper·음량·음성지문 공용 입력)
- `frames/%06d.jpg`: **1fps, 세로 720px**. OCR이 읽을 수 있는 최소 해상도(D2R 라벨 글자 9~27px@720p). 2시간 ≈ 7,200장 ≈ 500MB.
  - 기존 360p `thumbs/`는 폐기. `frame_motion`은 메모리에서 160×90으로 축소해 사용.
- `proxy.mp4`: **기본 생략**. `--proxy` 시 NVENC(h264_nvenc, cq 30)로 별도 패스. VLM/장면 검토용으로 필요할 때만.
- 디코딩: `-hwaccel cuda` 시도 → 실패 시 CPU. (현재 코드 유지)
- 예상 시간(2h 1080p60): 디코드+JPEG ≈ 8~12분, 오디오 ≈ 20초.

근거: 실측에서 디코드 3.7s/60s vs 프록시 포함 6s. 프록시가 시간의 40%를 먹는데 1차 신호들은 쓰지 않음.

### L1 signals — 교체 가능한 플러그인
인터페이스 유지: `@signal(name) def f(cache, profile) -> Curve | Events`. `profile`(게임 프로필) 인자만 추가.

| 신호 | 타입 | 출력 | 비고 |
|---|---|---|---|
| `audio_loudness` | Curve | dB rel. median, hop 0.5 | 현재 구현. 베이스라인 |
| `audio_spike` | Curve | 직전 5s 평균 대비 상승분 | e-kemeny 방식. 지속적 큰 소리(전투 BGM)와 "갑자기 큰 소리"를 구분 |
| `frame_motion` | Curve | 1fps 프레임차 | 현재 구현 |
| `ui_state` | Events(mask) | `{town, inventory, menu, loading, dungeon_select}` 구간 | 게임 프로필의 템플릿/색 ROI로 판정. **억제 마스크**로 사용 |
| `item_banner` | Events | `{t, added_text}` | **D2 1순위.** 좌상단 "득템 :" 배너 ROI를 3초 coarse OCR → 변화 구간만 1초, 안정 상태 전이에서 글자가 늘어난 시각을 이벤트로. 6.1절 참조 |
| `edit_emphasis` | Events | `{t_start, t_end, kind}` | **Phase 1 전용.** 편집본에서 배너 소실·흰 카드·타이틀 자막 구간 = 친구가 줌/카드로 강조한 지점. 쇼츠 후보 순위에 직접 반영 |
| `cut_density` | Curve | 30초 창 내 scdet 컷 수 | **Phase 1 전용.** 잘게 자른 구간 = 긴장. ffmpeg `scdet=t=10` 로그 파싱 |
| `d2_item_label` | Events | `{t, quality, text, matched_name}` | HSV 마스크(gold/green/orange/yellow) → 어두운 박스 contour → OCR → 이름 사전(rapidfuzz). 룬·유니크·세트만 이벤트. 배너에 안 적히는 드랍 보완용 |
| `dnf_result` | Events | 던전 클리어/결과창, 보스 HP 0 | 템플릿 매칭(TM_CCOEFF_NORMED ≥ 0.8) |
| `speech_keyword` | Events | 트랜스크립트에서 감탄사/키워드 시각 | faster-whisper(large-v3-turbo) 또는 ffmpeg whisper 필터. 한국어 사전은 `games/common.yaml` |
| `speech_energy` | Curve | 발화 구간의 음성 에너지(비BGM) | VAD 기반. 리액션 보강 |

캐시 키: `cache/<id>/<signal>.json`에 `meta.params_hash` 기록. 프로필/파라미터가 바뀌면 자동 재계산, 아니면 스킵.

### L2 decide — 판정 층
현재 `make_candidates`를 다음 순서로 확장:

1. **Events → Curve 어댑터**: 이벤트 하나를 비대칭 커널로 펼침. 기본 `[t-pre, t+post]` 사다리꼴(예: 룬 드랍 `pre=8, post=4`; 음성 키워드 `pre=30, post=5` — Auto-clipper 값). 커널 파라미터는 신호별로 프로필에.
2. **정규화**: Curve는 z-score(현재), Events 어댑터 출력은 0~1.
3. **가중합 + 동의 보너스**: `score = Σ w_i·s_i`, 0.2 이상인 신호가 2개면 ×1.15, 3개면 ×1.3.
4. **억제 마스크**: `ui_state`의 town/inventory/menu/loading 구간은 score×0 (또는 ×0.2). 메뉴에서 소리만 커지는 오탐 제거.
5. **임계 → 군집**: 임계 초과 → `merge_gap`(3~5s) 병합 → `clamp(span + pad, min_len, max_len)`.
6. **최소 보장**: 후보가 `duration/600`개 미만이면 임계를 ×0.5로 내려 보충(Auto-clipper fallback).
7. **evidence**: 각 후보에 `{signal: peak_value}`와 발화 이벤트 목록 기록. eval에서 "어느 신호가 잡았나"를 라벨별로 집계하는 데 쓴다.

판정 층은 나중에 같은 입력(신호 테이블)·같은 출력(Segments)을 내는 작은 분류기(로지스틱/GBDT)로 교체. 레이블 수백 개 쌓인 뒤.

### L3 eval — 결정의 근거
- 현재 `evaluate.py` 유지(recall / precision / coverage / 라벨별 / 놓친 구간).
- 추가: **신호별 기여도** — 각 정답 구간에서 어떤 신호가 임계를 넘었는지 → "rune_drop은 d2_item_label만 잡고 음량은 못 잡음" 같은 표.
- 추가: `sweep`에 가중치 그리드도 포함, 결과를 `reports/<id>_<ts>.md`로 저장해 실험 이력 남김.
- 허용 오차: 겹침 ≥ 1s(현재). 친구 컷은 보통 3~15s라 적절.

### `align` — 정답 데이터 자동 생성 (신규, 최우선)
> 조사한 모든 레포가 평가를 못 한 이유는 정답 만들기가 비싸서다. 친구의 **최종본**이 있으면 정답은 이미 존재한다.

- 입력: `finals/<id>.mp4`(유튜브 업로드본) + `cache/<id>/audio.wav`.
- 방법 A(1차): **오디오 랜드마크 지문**(Shazam식 스펙트로그램 피크 해시, 2~3초 창). 최종본의 각 창이 원본의 어느 시각에 매칭되는지 → 연속 매칭을 구간으로 병합 → `labels/<id>.csv`에 `label=kept, note=auto`.
  - BGM 추가·볼륨 변경·컷 전환에 강함. 발화/게임 효과음이 살아 있으면 매칭됨.
- 방법 B(보조): 프레임 pHash(2fps) 시퀀스 정렬. 오디오를 전부 바꾼 구간 대비.
- 검증: 합성 테스트 — 원본에서 임의 구간 10개를 잘라 BGM 섞어 붙인 가짜 최종본으로 recall 측정.
- 이후 사람이 하는 일은 자동 구간에 **라벨 범주만 붙이기**(rune_drop/reaction/fail/…). 30분 영상 라벨링이 2시간 → 10분.

### L4 output
- `export`: 후보를 mp4로 — NVENC로 교체(libx264 veryfast 대비 수 배 빠름). 파일명에 evidence 요약 포함(`012_0-19-30_2.1_loud+rune.mp4`).
- `harvest`: 현재 유지.
- `xml`(신규): xmeml v5 직접 생성. **마커와 세그먼트 트랙을 한 시퀀스에 둘 다** 넣는다(결정됨).
  - 리뷰 시퀀스(원본 해상도·fps): **V1 = 원본 전체 1클립**, **V2 = 후보 세그먼트만 원본 시각 위치에**(갭 유지), 시퀀스 마커 = 후보(이름 `score|evidence`, 색은 라벨별). 친구는 마커로 훑고 V2에서 리플 삭제하면 컷 편집본.
  - 쇼츠 시퀀스(Phase 1): 후보마다 **1080×1920 시퀀스 1개**. 클립에 `Basic Motion` 스케일/위치를 넣어 게임 화면 중앙(캐릭터 주변)이 보이게 크롭. 상단 여백은 제목용 빈 트랙. 득템 배너·채팅 오버레이는 크롭 밖으로 밀려나므로 필요하면 별도 PNG 트랙(후속).
  - 검토용 초안 mp4: 같은 크롭 파라미터로 NVENC 렌더(`export --shorts`). Premiere 열기 전에 빠르게 고르는 용도.
  - `pathurl`은 `file://localhost/C:/...` 형식, `<file>` id 재사용(AutoEditor 결함 회피).
  - OTIO는 나중 선택지(0.17+에서 어댑터가 별도 패키지로 분리됨). 1차는 직접 생성이 단순.

## 3. 게임 프로필 (데이터)

```yaml
# games/d2r.yaml
resolution_ref: [1920, 1080]      # ROI는 이 기준 비율로 저장, 실제 해상도에 스케일
item_colors:                       # HSV (OpenCV 0-180), d2r-image 차용
  gold:   [20, 75, 140, 26, 95, 230]
  green:  [56, 190, 190, 63, 255, 255]
  orange: [20, 190, 190, 23, 255, 255]
  yellow: [27, 110, 190, 33, 145, 255]
label_box: {min_h: 9, max_h: 27, min_w: 40, dark_mean: [4, 25]}
item_names: data/d2r_items.txt     # 룬 33 + 유니크 + 세트
ui_state:
  inventory: {roi: [0.02, 0.08, 0.30, 0.55], template: ui/inventory_frame.png, thr: 0.85}
  town:      {method: minimap_color}
events:
  d2_item_label: {pre: 8, post: 4, weight: 1.5, qualities: [orange, gold, green]}
```

```yaml
# games/common.yaml
speech_keywords: ["미쳤다", "대박", "와", "ㅋㅋ", "아니", "뭐야", "헐", "실화냐"]
speech_kernel: {pre: 30, post: 5, cooldown: 10}
```

DNF도 같은 틀(`games/dnf.yaml`): 결과창 템플릿, 보스 HP바 ROI, 던전 선택창 억제. 한국어 UI OCR은 RapidOCR(ONNX) 한국어 모델로 시작, 품질 부족하면 PaddleOCR.

근거: Auto-clipper의 "게임=설정 dict" 구조는 맞았지만 200KB 단일 파일·추상화 없음은 실패. 파일 분리 + 스키마 검증.

## 4. 저장소 레이아웃 (변경 후)

```
clipforge/
  clipforge/
    run.py            CLI (prep/signals/cands/eval/sweep/export/harvest/align/xml)
    preprocess.py     L0
    timeline.py       Curve/Segments(+Events 별칭)/parse_time
    profiles.py       games/*.yaml 로더+스키마 검증
    signals/          L1 플러그인 (base, audio_*, frame_motion, ui_state, d2_item_label, dnf_result, speech_*)
    adapters.py       Events → Curve 커널
    candidates.py     L2
    evaluate.py       L3
    align.py          최종본 ↔ 원본 정렬 → labels
    export_xml.py     xmeml 생성
  games/              d2r.yaml, dnf.yaml, common.yaml
  data/               d2r_items.txt, ui 템플릿 png
  videos/ finals/ cache/ review/ premiere/ reports/   (gitignore)
  labels/             정답 CSV (git 추적)
  docs/ARCHITECTURE.md
  tests/              합성 영상 기반 스모크 + align 합성 검증
```

## 5. 구현 순서 (각 단계가 지표를 바꾼다)

| # | 작업 | 끝났다는 기준 |
|---|---|---|
| 1 | 환경·스모크: 합성 영상으로 prep→signals→cands→eval 통과, git init | 한 번에 돈다 |
| 2 | prep 개편: frames 720p 1fps, proxy lazy, NVENC export | 2h 영상 prep ≤ 15분 |
| 3 | **align**: 합성 최종본으로 recall ≥ 95% | 친구 영상 1개에 자동 라벨 생성 |
| 4 | 베이스라인 숫자: 음량만으로 recall/coverage. 놓친 라벨 집계 | 첫 리포트 저장 |
| 5 | adapters + 동의보너스 + 억제마스크(`ui_state` D2R 인벤토리/마을) | precision 상승 확인 |
| 6 | `d2_item_label` (HSV→OCR→사전) | rune_drop recall 상승 |
| 7 | `speech_keyword` (faster-whisper 또는 ffmpeg whisper) | reaction recall 상승 |
| 8 | `xml` 출력 → 친구가 Premiere에서 열어 피드백 | 실사용 1회 |
| 9 | DNF 프로필·신호 | DNF 영상 1개 baseline |

## 6. 실제 최종본 1편에서 확인한 사실 (`래더 12기 59일차 지존참.mp4`, 2026-10-18 분석)

| 항목 | 관측 | 설계 반영 |
|---|---|---|
| 파일 | 11분 40초, **3840×2160 59.94fps** H.264 High 33.7Mbps, AAC 48k 스테레오, 2.9GB. 핸들러 `Mainconcept` = **Adobe Premiere/Media Encoder 출력** | 친구가 Premiere 사용 확정. xmeml 출력 방향 유지 |
| 게임 | **Diablo II: Resurrected 한국어 클라이언트**. 페이스캠 없음 | 프로필 `d2r.yaml`, 한국어 아이템명 사전 필요 |
| 오버레이(원본에 합성) | 좌하단 채팅 오버레이, 좌상단 후원 알림, **좌상단 "특템 :" 배너**(획득 아이템 누적 목록, OBS 텍스트), 우상단 게임명/난이도/공포의 영역 레벨 | 전부 원본 녹화에 들어 있음(방송 송출 화면 그대로). 아래 신호로 활용 |
| **특템 배너** | 영상 안에서 실시간 갱신. 11분 동안 스몰참→스웹벨트→레이븐링→말룬→기드참×2→에테강철그늘→탈라샤 갑옷→신타이탄→에테갑옷→드루횃불 추가 | **`item_banner` 신호 신설(D2 1순위)**: 배너 ROI를 1fps OCR → 텍스트가 길어지는 시각 = 드랍 직후. 바닥 라벨 OCR보다 쉽고 정확. 단순 픽셀 차분은 배경 이펙트 때문에 실패(실험 완료) → OCR 필수 |
| Premiere 추가물 | 인트로 타이틀(노란 자막 "래더 12기 노거래 맨땅 59일차"), 중간 설명 카드(흰 배경 텍스트, 현금 가치), 컷 전환 | `align`은 원본에 없는 구간(카드·타이틀)을 "매칭 없음"으로 버려야 함 |
| 편집 리듬 | scdet 컷 61개 / 11.7분 → **평균 10초마다 컷**, 5초 미만 간격 31개. 컷의 다수가 1~5초 무음 구간과 일치 | 친구는 **발화 단위로 잘게 자름**. align 지문 창은 ≤2초, 라벨 최소 겹침 1초 유지. 후보 `min_len` 3초는 적절 |
| 오디오 | 1초 RMS 중앙값 −21.3dBFS, p95 −17.2, 최대 −14.8. 다이내믹 레인지가 매우 좁음(마스터링됨) | 최종본 음량은 신호로 못 씀. 음량 신호는 **원본에서만** 계산. align은 음량이 아닌 지문(스펙트럼 피크)으로 |
| 4K 디코딩 비용 | NVDEC + 320p 축소 패스 = **4.1× 실시간**(11.7분 → 2분50초). 2시간 원본이 4K면 **패스당 ~30분** | prep은 **단일 패스**로 frames·audio를 동시에 뽑아야 함. 신호 함수는 절대 원본을 다시 읽지 않음(현 원칙 재확인) |
| OCR 글자 크기 | 4K 기준 배너 글자 높이 ≈45px, 바닥 아이템 라벨 ≈40px | 원본이 4K면 `frames/`는 **1080p**(라벨 20px)로. 배너 ROI는 별도로 네이티브 해상도 크롭 저장(`rois/banner/%06d.png`, 작음) |

> 아직 모름: 원본 녹화의 해상도/길이(최종본과 같은 4K60일 가능성 높음), 원본이 OBS 로컬 녹화인지 플랫폼 VOD인지, BGM 추가 여부.

### 6.1 `item_banner` 프로토타입 결과 (`experiments/banner_proto.py`, 같은 영상)
- RapidOCR 한국어 PP-OCRv5 mobile, CPU onnxruntime. 배너 크롭(1700×320) 1장 ≈ 1.4~2.0초. 3초 간격 + 변화 구간 정밀화로 631회 호출, 총 500초. → 1fps 전수 OCR은 비싸므로 **"3초 coarse → 변화 구간만 1초"** 전략을 신호 구현에 그대로 채택. GPU onnxruntime로 가면 수 배 단축 가능.
- 인식 품질: 아이템명 거의 정확(스웹벨트, 레이븐링, 말룬, 기드참(매찬34), 에테강철그늘, 탈라샤 갑옷, 신타이탄, 에테갑옷(방783)). 오인식 패턴: 득템→득렘/특램, 횃불→팻불, ★→츠. **프레임 간 jitter**가 있어 1초 단위 diff는 가짜 이벤트가 많음 → **3초 이상 유지된 "안정 상태" 간 전이**만 이벤트로 (구현에 반영).
- 검출된 득템 추가 이벤트: 4:54 스웹벨트, 6:45 레이븐링, 7:47 기드참(34), 8:33 기드참(23)+에테강철그늘, 10:59 탈라샤갑옷·신타이탄·에테갑옷·드루횃불(편집본이라 여러 개가 한 컷에 몰림). 영상 제목의 "지존참"(3맥20어레20피 스몰참)은 2:51~3:27 사이 추가.
- 모든 이벤트가 scdet 컷 군집(4:50~4:58, 6:52~6:59, 7:40~7:55, 8:27~8:45, 10:58)과 겹침 → 친구는 드랍 순간을 반드시 남긴다. Phase 2에서 이 신호 하나로 drop 계열 recall이 높을 것으로 기대.
- **배너 소실(RESET)도 신호**: 3:30~3:42 배너가 사라진 이유는 친구가 **채팅 오버레이를 줌인**한 편집("헐 지참 나왔어요??"). 즉 배너 RESET ≈ 줌/카드 삽입 ≈ **친구가 강조한 지점**. Phase 1(쇼츠)에서는 이게 가장 직접적인 "친구 취향" 신호. 신호명 `edit_emphasis`(줌·카드·타이틀 구간)로 추가.

## 7. 열린 결정 (사용자 확인 필요)
1. ~~디아블로2 버전~~ → **D2R 한국어, 페이스캠 없음** 확정.
2. **최종본 입수**: 유튜브 업로드본을 `finals/`에 넣을 수 있는가? (이번 파일처럼 Premiere 출력 원본이면 더 좋음)
3. **Premiere 출력 형태**: 마커만(V1) / 세그먼트 트랙(V2) / 둘 다. 친구가 10초 단위로 잘게 자르므로 V2(세그먼트 트랙)가 작업량을 더 줄일 것으로 예상.
4. **원본 스펙**: 원본 1편 샘플 필요. 4K60이면 prep 30분/2h를 전제로 설계.
5. **OCR 엔진**: 한국어 아이템명(배너·바닥 라벨) 필요 → RapidOCR 한국어 모델로 시작, 정확도 부족 시 PaddleOCR.
6. **특템 배너 규칙**: 친구가 어떤 기준으로 배너에 적는가(가치 있는 템만?). 배너 추가 시각과 최종본 보존 구간의 상관이 높다면 이 신호 하나로 rune_drop 계열 recall이 거의 해결됨.
