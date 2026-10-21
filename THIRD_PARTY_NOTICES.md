# 제3자 구성요소 고지

clipforge 의 소스 코드는 [MIT](LICENSE) 입니다. 아래 구성요소는 각자의 라이선스를 따르며, 설치본이 첫 실행 때 내려받는 런타임(`%LOCALAPPDATA%\clipforge\runtime`)이나 저장소에 함께 들어 있어요.

## 런타임에 함께 배포되는 것

| 구성요소 | 라이선스 | 비고 |
|---|---|---|
| Python (임베더블 배포판) | PSF License | python.org |
| FFmpeg (Gyan.dev full build) | **GPL v3** | 수정 없이 실행 파일로 동봉. 소스: [ffmpeg.org](https://ffmpeg.org) · 빌드: [gyan.dev](https://www.gyan.dev/ffmpeg/builds/). 라이선스 원문은 런타임 `bin/` 에 있어요 |
| faster-whisper · CTranslate2 | MIT | |
| Whisper large-v3-turbo (CTranslate2 변환본) | MIT | OpenAI Whisper · 변환본 mobiuslabsgmbh/faster-whisper-large-v3-turbo |
| CTranslate2 휠에 함께 든 Intel OpenMP 런타임 · cuDNN DLL | Intel · NVIDIA 재배포 라이선스 | PyPI 의 `ctranslate2` 휠을 수정 없이 그대로 넣어요 |
| RapidOCR · ONNX Runtime · PP-OCR 모델 | Apache-2.0 · MIT · Apache-2.0 | |
| FastAPI · uvicorn · Pillow · numpy · PyYAML · rapidfuzz · fonttools · OpenTimelineIO | MIT · BSD · HPND · Apache-2.0 | |

## 앱이 공급처에서 직접 받는 것

| 구성요소 | 라이선스 | 비고 |
|---|---|---|
| NVIDIA cuBLAS · cuDNN · NVRTC (GPU 가속, 선택) | NVIDIA 소프트웨어 라이선스 | NVIDIA GPU 가 있을 때 처음 실행에서 PyPI(`files.pythonhosted.org`)의 NVIDIA 휠을 그대로 받아요. 이 저장소의 릴리스에는 들어 있지 않아요 |

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
