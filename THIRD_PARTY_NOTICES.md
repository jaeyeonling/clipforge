# 제3자 구성요소 고지

clipforge 의 소스 코드는 [MIT](LICENSE) 입니다. 아래 구성요소는 각자의 라이선스를 따르며, 설치본이 첫 실행 때 내려받는 런타임(`%LOCALAPPDATA%\clipforge\runtime`)이나 저장소에 함께 들어 있어요.

## 런타임에 함께 배포되는 것

| 구성요소 | 라이선스 | 비고 |
|---|---|---|
| Python (임베더블 배포판) | PSF License | python.org |
| FFmpeg (Gyan.dev full build) | **GPL v3** | 수정 없이 실행 파일로 동봉. 소스: [ffmpeg.org](https://ffmpeg.org) · 빌드: [gyan.dev](https://www.gyan.dev/ffmpeg/builds/). 라이선스 원문은 런타임 `bin/` 에 있어요 |
| faster-whisper · CTranslate2 | MIT | |
| Whisper large-v3-turbo (CTranslate2 변환본) | MIT | OpenAI Whisper · 변환본 mobiuslabsgmbh/faster-whisper-large-v3-turbo |
| NVIDIA cuBLAS · cuDNN (pip 휠, 선택) | NVIDIA 소프트웨어 라이선스 | NVIDIA GPU 가 있을 때만 받아요. 재배포 조건은 각 휠의 라이선스를 따라요 |
| RapidOCR · ONNX Runtime · PP-OCR 모델 | Apache-2.0 · MIT · Apache-2.0 | |
| FastAPI · uvicorn · Pillow · numpy · PyYAML · rapidfuzz · fonttools · OpenTimelineIO | MIT · BSD · HPND · Apache-2.0 | |

## 저장소에 들어 있는 것

| 구성요소 | 라이선스 | 위치 |
|---|---|---|
| 나눔펜스크립트 (Nanum Pen Script) | SIL Open Font License 1.1 | `assets/fonts/`, 원문 `OFL-NanumPenScript.txt` |
| 검은고딕 (Black Han Sans) | SIL Open Font License 1.1 | `assets/fonts/`, 원문 `OFL-BlackHanSans.txt` |
| 디아블로2 아이템 데이터 | 데이터 가공: [blizzhackers/d2data](https://github.com/blizzhackers/d2data) (MIT) | `data/d2r/items.json` (`scripts/build_items.py` 로 생성). 게임 데이터와 아이템 이름은 Blizzard Entertainment 의 것이에요 |

## 화면·데스크톱

| 구성요소 | 라이선스 |
|---|---|
| React · Vite (빌드 산출물 `app/dist`) | MIT |
| Electron · electron-builder · electron-updater · ws | MIT |
| 7-Zip (7za.exe, 구성요소 압축 해제) | LGPL-2.1 + unRAR 제한 · [7-zip.org](https://www.7-zip.org) |

Diablo II 와 Diablo II: Resurrected 는 Blizzard Entertainment, Inc. 의 상표예요. clipforge 는 Blizzard 와 관계가 없고 승인받은 제품도 아니에요.
