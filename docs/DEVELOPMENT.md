# 개발 안내

clipforge 는 세 덩어리로 나뉩니다. 각자 따로 띄우고 고칠 수 있어요.

| 폴더 | 무엇 | 실행 |
|---|---|---|
| `clipforge/` | 분석 엔진 (Python 3.12). 전처리 → 신호 → 후보 → 렌더 → Premiere XML. HTTP + WebSocket API | `python -m clipforge.app` |
| `app/` | 화면 (React 18 + TypeScript + Vite). 엔진이 빌드 결과를 그대로 서빙 | `npm run dev` / `npm run build` |
| `desktop/` | 데스크톱 껍데기 (Electron). 엔진을 자식 프로세스로 띄우고 트레이·알림·업데이트를 맡음 | `npm start` |

구조는 [ARCHITECTURE.md](ARCHITECTURE.md), 분석 코어는 [ENGINE.md](ENGINE.md), 문서 전체 지도는 [docs/README.md](README.md) 에 있어요.

## 준비 (Windows)

```powershell
winget install Gyan.FFmpeg                 # ffmpeg (설치 뒤 터미널 재시작)
python -m venv .venv ; .\.venv\Scripts\activate
pip install -r requirements.txt            # NVIDIA GPU 가 없으면 nvidia-* 두 줄은 빼도 돼요
cd app ; npm install ; npm run build ; cd ..
cd desktop ; npm install ; cd ..
```
Node 는 22 를 씁니다. 포터블 Node 를 쓰면 `CLIPFORGE_NODE_DIR` 로 폴더를 알려 주세요.

## 띄우기

```powershell
python -m clipforge.app                    # 엔진 + 화면: http://127.0.0.1:8765 (127.0.0.1 전용)
cd app ; npm run dev                       # 화면 개발 서버 5173, /api·/ws·/media 는 8765 로 프록시
cd desktop ; npm start                     # 데스크톱 창. 8765 에 엔진이 떠 있으면 그것에 붙어요
```
데이터(영상·캐시·판정)는 기본으로 저장소 폴더에 쌓여요. `CLIPFORGE_DATA=<폴더>` 로 분리할 수 있어요.
엔진 코드를 고치면 떠 있는 엔진을 다시 시작해야 새 단계가 보여요.

## 테스트

```powershell
python -m pytest                           # 엔진 53개 (ffmpeg·GPU 없이 돌아요)
scriptseck.ps1                          # CI 와 같은 검사를 한 번에 (lint · 포맷 · 테스트 · 빌드)
cd desktop ; npm test                      # 구성요소 다운로드·설치·패키징 9개
cd app ; npm test                          # 화면 37개 (Vitest)
cd app ; npm run build                     # 타입 검사 + 빌드
cd desktop ; npm run smoke                 # 창·엔진이 실제로 뜨는지 5초 점검 (로그 %APPDATA%\clipforge\shell.log)
```

## 분석 코어를 직접 돌리기 (CLI)

화면 없이 단계별로 돌리고 지표를 보는 실험 하네스예요. "신호 하나 추가 → recall 변화 확인" 사이클을 분 단위로 만드는 게 목적입니다.

```
원본 mp4 ─prep─▶ cache/<id>/ (meta.json, audio.wav, frames/ 1fps≤1080p, rois/<name>/ 네이티브 크롭)
                   │
            signals ▼  Curve/Segments JSON  (audio_loudness, item_banner, chat_burst, … 플러그인)
                   │
              cands ▼  candidates.json      (가중합 + 임계값)
                   │
      ┌── eval ◀───┴───▶ export ── review/<id>/*.mp4 ─(사람이 keep/로 이동)─ harvest ──▶ labels/<id>.csv
      │   recall / precision / coverage / 놓친 구간                                       ▲
      └───────────────── labels/<id>.csv (정답: 실제로 남긴 구간) ──────────────────────┘
```

```powershell
python -m clipforge.run prep videos\ep01.mp4 [--game d2r] [--proxy]   # 단일 패스로 오디오·프레임·ROI 크롭 (NVDEC 자동 시도)
python -m clipforge.run transcribe ep01                                # Whisper 전사 → cache/ep01/transcript.json
python -m clipforge.run signals ep01
python -m clipforge.run cands ep01
python -m clipforge.run eval ep01                                      # recall / coverage / 놓친 구간
python -m clipforge.run sweep ep01 --w audio_loudness=1 --w frame_motion=0.5
python -m clipforge.run shorts ep01 ; python -m clipforge.run export ep01 --shorts --k 5
```
정답 표는 `labels/<id>.csv` (`start,end,label,note`, 시간은 mm:ss 또는 초). `labels/_template.csv` 를 참고하세요.

`eval` 에서 볼 것:
- **recall**: 정답 중 몇 %를 후보가 덮었나. 1순위 지표.
- **coverage**: 사람이 검토해야 할 영상 비율. 비용 지표 (목표 예: recall ≥ 95%, coverage ≤ 10%).
- **놓친 구간 · 라벨별 recall**: 다음에 어떤 신호를 만들어야 하는지 알려줘요.

### 원본 ↔ 편집본 정렬 (Phase 2)
```powershell
python -m clipforge.run prep <원본>
python -m clipforge.run align <원본> --final <편집본.mp4>      # 살아남은 구간 → labels/<원본>.csv
python -m clipforge.run align <편집본> --shorts <쇼츠.mp4|폴더>  # 올린 쇼츠를 편집본에 역매핑 → 쇼츠 정답
python -m clipforge.run eval <원본>
```
설계: [design/ALIGN.md](design/ALIGN.md) (오디오 랜드마크 지문, 창 투표, 경계 다듬기).

## 신호 추가하기

`clipforge/signals/` 에 파일 하나를 만들고 `__init__.py` 에 import 한 줄을 넣으면 돼요.

```python
from ..timeline import Segments, Segment
from .base import signal


@signal("my_signal")
def my_signal(cache: Path) -> Segments:
    # cache/rois/<name>/*.jpg 나 cache/frames/*.jpg, cache/audio.wav 를 읽어 구간을 돌려준다
    ...
```
Curve(연속값)든 Segments(이벤트)든 공통 포맷으로 내놓으면 `cands`·`eval`·`shorts` 가 그대로 써요.
게임별 화면 영역과 신호 묶음은 `games/<game>.yaml` 과 `games/common.yaml` 에서 정합니다.

| 신호 | 입력 | 설명 |
|---|---|---|
| `audio_loudness` | audio.wav | RMS dB, 중앙값 대비 |
| `frame_motion` | frames/ | 1fps 프레임 간 차이. 정적 구간 탐지 |
| `item_banner` | rois/banner | 득템 배너 OCR, 새 아이템이 적히는 순간 |
| `chat_burst` · `chat_text` | rois/chat | 채팅 오버레이 변화율 · OCR 새 메시지 |
| `speech_keyword` | transcript.json | 리액션·득템 어휘 발화 |
| `cut_density` · `edit_emphasis` | frames/ | 편집본의 컷 밀도 · 줌 강조 |
| `ui_state` | frames/ | 인벤·툴팁 패널 상태 (세로 크롭 중심) |

## 라이브 (방송 중)

화면을 1초에 한 장 보고 세트·유니크 아이템 라벨이 뜨면 "배너에 추가?" 제안을 올려요 (승인 모드). 승인하면 득템 배너 텍스트와 OBS 텍스트 소스가 바뀌고 북마크가 남아요.
OBS 연동: OBS → 도구 → WebSocket 서버 설정(포트 4455) → 라이브 탭에서 연결 확인 → 텍스트 소스 선택. 설계·검증: [design/LIVE.md](design/LIVE.md).

## 배포

설치본·앱 내 업데이트·오프라인 USB 묶음은 [desktop/README.md](../desktop/README.md) 에 정리돼 있어요.

```powershell
python scripts\build_engine_dist.py --smoke             # 포터블 런타임(engine-dist/) 구성 + 번들 파이썬으로 health 확인
python scripts\publish_github.py runtime                # 구성요소 릴리스 (처음 한 번·런타임이 바뀔 때)
python scripts\publish_github.py app                    # 앱 릴리스: 화면 빌드 → 엔진 코드 zip·latest.json → NSIS → 업로드
python scripts\make_usb_release.py --out E:\clipforge   # 인터넷 없이 전달하는 폴더
```
