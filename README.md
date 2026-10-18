# clipforge — 게임 영상 하이라이트 실험 하네스

"무엇이 좋은 편집인지 측정 가능하게 만들고, 신호를 바꿔 끼우며 지표로 결정한다"는 원칙을 코드로 옮긴 최소 뼈대.
모델 선택은 나중 문제. 지금 이 하네스가 하는 일은 딱 하나 — **신호 하나 추가 → recall 변화 확인** 사이클을 분 단위로 만드는 것.

```
원본 mp4 ─prep─▶ cache/<id>/ (audio.wav, proxy.mp4, thumbs/, meta.json)
                   │
            signals ▼  Curve/Segments JSON  (audio_loudness, frame_motion, ... 플러그인)
                   │
              cands ▼  candidates.json      (가중합 + 임계값. 나중에 분류기로 교체)
                   │
      ┌── eval ◀───┴───▶ export ── review/<id>/*.mp4 ─(사람이 keep/로 이동)─ harvest ──▶ labels/<id>.csv
      │   recall / precision / coverage / 놓친 구간                                       ▲
      └───────────────── labels/<id>.csv (정답: 친구가 실제로 남긴 구간) ────────────────┘
```

## 설치 (Windows)

```powershell
# ffmpeg 필요: winget install Gyan.FFmpeg  (설치 후 터미널 재시작)
cd C:\Users\jaeye\source\clipforge
python -m venv .venv ; .\.venv\Scripts\activate
pip install -r requirements.txt
```

## 첫 실험 (친구 영상 1개로 30분)

```powershell
# 1. 원본 영상을 videos/ 에 넣고 전처리 (2시간 영상 기준 수 분. NVDEC 자동 시도)
python -m clipforge.run prep videos\ep01.mp4

# 2. 정답 만들기: 친구 최종본을 보면서 "원본에서 어느 구간이 살아남았나"를 labels\ep01.csv 에 적는다
#    start,end,label,note   (시간은 mm:ss 또는 hh:mm:ss, label은 rune_drop / reaction / fail / explain / clear 등 자유)
#    labels\_template.csv 참고. 이 표 한 장이 프로젝트에서 제일 중요한 산출물.

# 3. 신호 계산 → 후보 생성 → 평가
python -m clipforge.run signals ep01
python -m clipforge.run cands ep01
python -m clipforge.run eval ep01
```

`eval` 출력에서 봐야 할 것:
- **recall** — 정답 중 몇 %를 후보가 덮었나. 1순위 지표.
- **coverage** — 검토해야 할 영상 비율. 비용 지표. (목표 예: recall ≥ 95%, coverage ≤ 20%)
- **놓친 구간 / 라벨별 recall** — 다음에 어떤 신호를 만들어야 하는지 데이터가 알려줌.
  음량만으로 `reaction`은 잡히는데 `rune_drop`을 전부 놓친다면 → OCR 신호가 다음 과제.

```powershell
# 임계값/가중치 스윕
python -m clipforge.run sweep ep01
python -m clipforge.run sweep ep01 --w audio_loudness=1 --w frame_motion=0.5

# 후보를 클립으로 잘라 검토 → 쓸 것만 review\ep01\keep\ 로 이동 → 레이블로 회수
python -m clipforge.run export ep01
python -m clipforge.run harvest ep01
```

## 신호 추가하기

`clipforge/signals/` 에 파일 하나 만들고 `__init__.py` 에 import 한 줄.

```python
from ..timeline import Segments, Segment
from .base import signal

@signal("d2_item_drop")
def d2_item_drop(cache: Path) -> Segments:
    # cache/thumbs/*.jpg 를 d2r-image / PaddleOCR 로 읽어 룬·유니크 이름이 보이는 초를 구간으로
    ...
```

Curve(연속값)든 Segments(이벤트)든 공통 포맷으로만 내놓으면 `cands`/`eval`이 그대로 돈다.
`candidates.py`의 `DEFAULT_WEIGHTS`에 이름을 추가하면 가중합에 들어간다. (Segments 신호는 아직 Curve로 변환하는 어댑터가 없음 — 다음 단계)

## 다음 단계 (우선순위 순)

1. **정답 데이터**: 친구 영상 3~5개로 `labels/` 채우기. 라벨 범주 확정.
2. **베이스라인 숫자**: 음량만으로 recall 몇 %인지. 놓친 라벨이 뭔지.
3. 놓친 라벨에 맞는 신호 추가 — 예상: Whisper 키워드(리액션 보강), d2r-image OCR(조용한 드랍), 던파 결과창 템플릿 매칭
4. Segments → Curve 어댑터, 판정 층을 작은 분류기로 교체
5. 렌더 층: candidates → 프리미어 XML / OTIO (AutoEditor 방식)

## 내장 신호

| 이름 | 입력 | 설명 |
|---|---|---|
| `audio_loudness` | audio.wav | RMS dB, 중앙값 대비. hop 0.5s |
| `frame_motion` | thumbs/ | 1fps 썸네일 간 평균 절대 차이. 정적 구간 탐지용 |
