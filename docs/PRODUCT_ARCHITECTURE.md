# clipforge 제품 아키텍처 — 방송용 통합 프로그램으로 가는 설계 (v0, 2026-10-18)

> 지금까지의 `clipforge` 는 "편집본 → 쇼츠 후보" 실험 하네스다. 이 문서는 그것을 **스트리머가 방송 전·중·후에 쓰는 하나의 프로그램**으로
> 키울 때의 설계다. 실험 하네스의 원칙(정답 데이터 먼저, 신호는 플러그인, 지표로 결정)은 그대로 제품의 원칙이 된다.
> 가정은 `[가정]` 으로 표시했고, 끝의 §10 에 결정 요청을 모았다.

## 1. 무엇을 만드는가

**한 문장**: 게임 방송의 "순간"을 자동으로 찾고, 기록하고, 콘텐츠(쇼츠·편집 포인트·오버레이)로 바꿔 주는 스트리머용 로컬 프로그램.

사용 시점별 기능 (`[가정]` 친구 = 디아2R·던파 방송, OBS, Premiere, 페이스캠 없음, 4K60):

| 시점 | 기능 | 지금 상태 |
|---|---|---|
| 방송 중 (Live) | **득템 배너 자동 갱신** — 게임 화면에서 드랍/감별을 읽어 OBS 텍스트 소스를 갱신 (지금은 메모장에 수동 입력). 아이템 가치 툴팁. **하이라이트 북마크**(단축키 또는 자동: 채팅 폭주·리액션) → 방송 후 파이프라인의 앵커. 리플레이 버퍼 저장 트리거. | 없음 |
| 방송 직후 (Post) | 원본 VOD → 편집 포인트(Premiere 마커·세그먼트 트랙), 쇼츠 초안(mp4+SRT+세로 시퀀스), 득템 로그. | 편집본 입력으로 동작 중 (Phase 1). 원본 입력은 Phase 2 |
| 상시 | 득템 기록·시세 노트(value), 어휘 사전, 회차 아카이브, 지표 대시보드(hit@K, recall). | 파일 기반 일부 |

**비목표** (v1 에서 하지 않음): 업로드 자동화, 자막 번역, 완전 자동 편집, 다른 스트리머 지원(멀티 프로필은 구조만 준비).

## 2. 설계 원칙

1. **타임라인이 중심 데이터**. 모든 것은 (시각, 구간, 값) 이다 — 신호, 이벤트, 후보, 정답, 사람의 판정, 라이브 북마크. 라이브와 포스트가 같은 모델(`Curve / Segments`)을 쓴다.
2. **코어와 껍데기 분리**. 분석 엔진(Python)과 데스크톱 UI 는 **프로세스 경계**로 나누고 JSON 계약으로만 대화한다. UI 언어는 엔진과 무관하게 고를 수 있어야 한다.
3. **플러그인 3종**: 게임 프로필(데이터), 신호(함수), 출력(렌더러/익스포터). 새 게임·새 신호·새 출력이 코어 수정 없이 들어온다.
4. **모든 긴 작업은 Job**. 진행률·취소·재개·로그가 있고, 단계별 캐시로 재실행이 싸다.
5. **측정 없이는 바꾸지 않는다**. 규칙·가중치 변경은 라벨 셋에 대한 지표 변화와 함께 기록한다 (지금의 `experiments/`, `labels/` 가 제품의 평가 셋으로 승격).
6. **로컬 우선, 네트워크는 선택**. 영상·채팅·전사는 PC 밖으로 나가지 않는다. 모델·사전 갱신만 명시적 다운로드.
7. **방송을 방해하지 않는다**. 라이브 모듈은 OBS 와 GPU 인코더(NVENC)를 두고 경쟁하지 않는다 — CPU/경량 GPU 추론, 저주기(1~2fps), 실패 시 조용히 비활성.

## 3. 전체 구조

```
┌──────────────────────────── Desktop Shell (UI) ─────────────────────────────┐
│  프로젝트/회차 관리 · 작업 큐 · 후보 리뷰(재생, keep/no+사유) · 설정 · 캘리브레이션 · 대시보드 │
│  Electron(TypeScript) 껍데기 + 웹 UI(React)  — OP.GG 데스크톱 방식 [Windows 우선]   │
└───────────────▲──────────────────── JSON-RPC over stdio ──────────────────────┘
                │ (engine 를 자식 프로세스로 실행, 줄 단위 JSON 요청/응답/진행 이벤트)
┌───────────────┴──────────────────── Engine (Python) ────────────────────────┐
│  api/        rpc 서버(stdio JSON Lines·HTTP+WS), Job 러너(진행률·취소·로그), 파일 시스템 │
│  core/       timeline, profiles, adapters, candidates, shorts, evaluate (지금 코드)   │
│  signals/    플러그인 레지스트리 (item_banner, chat_text, speech_keyword, ui_state …)  │
│  io/         preprocess(ffmpeg), transcribe(whisper), ocr(rapidocr) — 외부 도구 어댑터  │
│  outputs/    render(세로 mp4), subtitles, export_xml(Premiere), reports            │
│  live/       화면 캡처 → 경량 신호 → OBS WebSocket(텍스트 소스) · 북마크 · 리플레이 트리거 │
└───────────────┬──────────────────────────────────────────────────────────────┘
                │ subprocess / 파일
   ffmpeg (NVDEC·NVENC·libass·scdet) · ONNX Runtime(OCR) · CTranslate2(Whisper) · OBS(WebSocket 5)
```

왜 프로세스 경계인가: Python 은 ML 생태계 때문에 엔진으로 최적이고, 배포·GUI 는 약점이다. 경계를 두면 (a) UI 를 웹 기술로 만들어 Electron 껍데기에 넣고 (b) 나중에 안정된 엔진 부품을 Rust/C# 으로 옮겨도 UI 가 모른다. 통신은 **stdio JSON Lines** 로 시작한다 — 포트·방화벽·보안 걱정이 없고 UI 가 엔진 수명을 소유한다. 웹 UI 가 필요해지면 같은 메서드를 HTTP 로 노출한다.

## 4. 엔진 API (계약 초안)

요청 `{"id", "method", "params"}` / 응답 `{"id", "result" | "error"}` / 이벤트 `{"event", "job_id", ...}`.

| 메서드 | 설명 |
|---|---|
| `project.open(path)` / `project.list_episodes()` | 프로젝트 폴더(아래 §6) 열기, 회차 목록 |
| `episode.add(video_path, game?, title?)` | 영상 등록 → 회차 id, 프로필 추정 |
| `job.run(episode, stages=["prep","transcribe","signals","shorts","export","xml"], params)` | 파이프라인 실행 → job_id. 이벤트 `job.progress {stage, pct, eta, msg}`, `job.log`, `job.done`, `job.error {code, hint}` |
| `job.cancel(job_id)` | 취소 (ffmpeg/OCR 프로세스 종료, 캐시는 유지) |
| `candidates.list(episode)` | 후보(순간 순위) + 근거 + 자막 제안 + 미리보기 경로 |
| `decision.set(episode, candidate_id, keep|no, reason?)` | 판정 → labels 반영 (index.md/keep 폴더 수동 흐름 대체) |
| `calibrate.check(episode)` / `calibrate.preview(episode)` | ROI 점검 결과(배너 OCR 적중률, 패널 제목 검출률, 채팅 검출률) + ROI 박스 그린 프레임 |
| `profile.get/set(game)` | 게임 프로필 읽기·수정 (ROI 드래그 조정 → 저장) |
| `metrics.summary()` | 회차별 hit@K·recall·라벨 수 |
| `live.start(config)` / `live.stop()` / `live.mark(note)` | 라이브 모듈 (§7) |
| `engine.health()` | ffmpeg/GPU/모델/폰트 상태 (첫 실행 진단) |

오류는 코드 + 사람용 힌트를 함께 낸다 (`E_FFMPEG_MISSING: "ffmpeg 를 찾지 못했습니다. 설치 폴더의 bin/ 을 확인하세요"`). 트레이스백은 로그 파일로만.

## 5. 플러그인 계약

- **게임 프로필** (`games/<game>.yaml`, 스키마 버전 명시): ROI(비율), 색 범위, 패널 제목 키워드, 이벤트 커널, 신호 가중치, 억제 규칙. **캘리브레이션 데이터**(검증한 해상도·날짜·샘플 프레임 해시)를 함께 저장해 "이 프로필이 지금 화면과 맞는가"를 판정할 수 있게.
- **신호** (`@signal(name, needs=["frames","rois.banner"], produces="events|curve", cost="cpu-heavy|gpu|light")`): 입력 의존성을 선언해 Job 러너가 순서·병렬·캐시 무효화를 결정. 파라미터 해시가 캐시 키.
- **출력** (`@output(name)`): 후보 목록 + 프로젝트 → 파일. 세로 mp4, SRT, Premiere XML, 득템 로그 CSV, (후속) 썸네일.
- **라이브 신호**는 같은 인터페이스에 `mode="live"` — 프레임 1장과 최근 N초 상태를 받아 이벤트를 낸다. 포스트 신호 중 경량인 것(배너 OCR, 패널 제목)은 두 모드 공용.

## 6. 데이터와 파일 레이아웃

```
<Project>/                      ← 사용자가 고르는 폴더 (OneDrive 밖 권장)
  project.json                  스키마 버전, 게임, 스트리머 프로필 참조
  episodes/<id>/
    source.json                 원본 경로·메타 (영상은 복사하지 않고 참조)
    cache/                      prep·신호·전사·OCR (재생성 가능, 삭제해도 됨)
    labels.csv                  사람 판정 + 약한 정답 (영구, 백업 대상)
    outputs/<run_ts>/           초안 mp4·srt·xml·index (run 마다 폴더, 덮어쓰지 않음)
    live/                       방송 중 북마크·득템 로그·배너 히스토리
  profiles/                     스트리머 오버레이 레이아웃(캘리브레이션 결과), 어휘·가치 사전 개인 보강분
  metrics/                      회차별 지표 스냅샷
<App>/                          ← 프로그램 설치 폴더 (업데이트로 교체되는 영역)
  engine/ (python runtime + packages), bin/ffmpeg, models/, fonts/, games/(기본 프로필), data/(d2data 사전)
```
원칙: **사용자 데이터(라벨·판정·프로필 보강)와 앱(코드·모델·기본 사전)을 분리**해 업데이트가 판정을 지우지 않게. 모든 JSON/CSV 에 `schema_version`, 엔진에 마이그레이션 함수.

## 7. 라이브 모듈 (방송 중) — 설계 제약이 가장 큰 부분

- 입력: 게임 창 캡처(Windows Graphics Capture, 1~2fps) 또는 OBS 가상카메라/소스 스크린샷(obs-websocket `GetSourceScreenshot`). `[가정]` 캡처는 CPU 복사 1장/초 수준이라 방송 부하에 영향 없음 — 실측 필요.
- 신호: 패널 제목 OCR(인식 전용, 초당 수 ms), 득템 감지(바닥 라벨 색 마스크 + 툴팁 OCR — Phase 2 의 `d2_item_label`), 채팅 폭주(플랫폼 API 또는 채팅 오버레이 OCR), 음성 키워드(라이브 Whisper 는 무거워 v1 제외).
- 출력: OBS WebSocket 5 로 **텍스트 소스 갱신**(득템 배너 자동), 선택적으로 리플레이 버퍼 저장, `live/bookmarks.json`(시각·종류·근거) — 방송 후 파이프라인이 앵커로 읽는다.
- 안전장치: GPU 사용 금지(ONNX CPU), 실패 시 배너 갱신 중단 + 알림, 사용자 확인 모드(감지한 아이템을 바로 쓰지 않고 "추가하시겠습니까?" 토스트 → 단축키 승인) 기본 ON. 득템 오탐이 방송에 그대로 나가는 게 가장 큰 리스크.
- 시간 동기: 라이브 북마크의 시각은 OBS 녹화 타임코드 기준으로 저장(`GetRecordStatus` 의 출력 시간). 방송 후 VOD 와 1:1 대응.

## 8. 품질·테스트·운영

- **단위 테스트**: timeline/adapters/candidates/shorts 의 순수 함수 (pytest). 지금 코드 중 ffmpeg·OCR 에 의존하지 않는 부분부터.
- **골든 테스트**: ep59 캐시 일부(배너 OCR·전사·채팅 JSON)를 픽스처로 고정 → 후보·점수·자막이 바뀌면 diff 로 보이게. 규칙 변경이 의도한 변화인지 확인.
- **합성 스모크**: 합성 영상(배너 텍스트·채팅 텍스트를 drawtext 로 넣은 1분짜리)으로 prep→signals→shorts→export 전 과정. GPU 없는 CI(GitHub Actions Windows 러너)에서 CPU 경로 검증.
- **폰트/모델 검사**: `scripts/check_fonts.py` 처럼 외부 자산이 바뀔 때 도는 검사. 모델 파일 해시 고정.
- **관측**: 구조화 로그(JSON Lines), run 매니페스트(파라미터 해시·버전·소요 시간), 회차별 지표 스냅샷. UI 대시보드는 이 파일만 읽는다.
- **에러 등급**: 사용자 조치 가능(ffmpeg 없음, 디스크 부족, 프로필 불일치) vs 내부 오류(로그+재현 정보 수집). 전자는 힌트 문장 필수.
- **업데이트**: 앱 폴더 교체 + 데이터 마이그레이션. 버전 호환 표를 project.json 에.

## 9. 언어·배포 결정 (제안)

| 층 | 선택 | 이유 |
|---|---|---|
| 엔진 | **Python 유지** | ML 생태계·실험 속도. 병목은 ffmpeg/GPU 추론이라 언어 속도 무관. 포터블 런타임으로 동봉 |
| UI | **Electron + React/TypeScript** (2026-10-18 결정, §9.1) | OP.GG 데스크톱처럼 "웹앱 기반인데 데스크톱 완성도". 자동 업데이트·트레이·알림·오버레이 생태계가 가장 성숙. 번들 크기는 엔진(CUDA·모델)에 비하면 무시 가능 |
| 라이브 캡처·OBS 연동 | 엔진 `live/` (Python: Windows Graphics Capture/obs-websocket) | 껍데기는 표시·승인 UI 만. 성능이 문제면 캡처만 네이티브 모듈로 |
| 외부 도구 | ffmpeg(Gyan full, GPL 고지 동봉), ONNX Runtime, CTranslate2, obs-websocket 5 | 모두 번들 가능. 라이선스 고지 파일 1개로 정리 |
| 패키징 | 설치 폴더 zip → 이후 Inno Setup/MSIX | PyInstaller 단일 exe 는 CUDA/ONNX DLL 때문에 비권장 |

안정된 뒤 Rust 로 옮길 후보: ffmpeg 호출·파일 처리·렌더 조립(변하지 않는 부분). 신호·판정 로직은 라벨이 수천 개가 되기 전까지 Python 에 둔다.

### 9.1 껍데기 결정 (2026-10-18): "웹앱 기반인데 데스크톱 완성도" — OP.GG 데스크톱 방식

기대치: OP.GG 데스크톱 앱처럼 화면은 웹 기술로 만들되 설치·실행·상주·알림이 네이티브 앱 수준. OP.GG 데스크톱은 Electron 위에 웹 UI 를 올린 구조다. 우리도 같은 길을 간다.

| 후보 | 장점 | 단점 | 판단 |
|---|---|---|---|
| **Electron** | 가장 성숙(자동 업데이트 electron-updater, 트레이, 알림, 게임 오버레이 사례, 크래시 리포트), OP.GG·Discord 가 쓰는 검증된 길 | 번들 ~150MB, 메모리 ~200MB | **채택**. 엔진이 CUDA·모델로 1GB 를 넘으므로 크기 차이는 의미 없음 |
| Tauri 2 | 작고 가벼움, 사이드카·업데이터 내장 | Rust 셸 코드, 오버레이·생태계 얇음, WebView2 버전 편차 | 보류. 크기가 문제될 때만 |
| C#/WPF + WebView2 | 기존 스택 | 패키징·업데이트·UI 도구를 직접 조립, 웹 UI 와 네이티브 두 벌 관리 | 탈락 |

구조: Electron 메인 프로세스가 Python 엔진을 **사이드카로 실행**하고 `api/stdio.py`(JSON Lines)로 대화한다. 렌더러(React)는 IPC 로 메인에게 요청. 개발 중에는 렌더러가 `127.0.0.1:8765` HTTP+WS 를 직접 써도 된다(지금 `ui/` 가 그 모드). 엔진 메서드는 둘 다 같은 `Engine` 객체.

"완성도"의 구체 항목 (OP.GG 에서 당연히 되는 것들 = 우리의 완료 기준):
1. 설치본 하나(NSIS) + 자동 업데이트, 첫 실행 진단(ffmpeg/GPU/모델/폰트 → `engine.health`)과 안내.
2. 트레이 상주, 작업 완료·오류 알림, 창 닫아도 작업은 계속.
3. 게임/OBS 실행 감지 → 라이브 모듈 자동 시작(승인 모드), 방송 종료 → 포스트 파이프라인 제안.
4. 일관된 디자인 시스템(다크 기본, 브랜드 노랑 포인트), 키보드 조작, 빈 상태·로딩·오류 화면 전부 설계.
5. 오프라인 동작, 로그·크래시 수집(로컬 파일, 전송은 사용자 동의).
6. 긴 작업은 진행률·ETA·취소가 항상 보인다(지금 Job 러너가 제공).

이행 순서: ✅ React+Vite 화면(`app/`, 2026-10-18 밤) → Electron 껍데기(사이드카·트레이·업데이터) → NSIS 설치본. 엔진 API 는 변하지 않으므로 UI 교체가 엔진 작업을 막지 않는다.

**`app/` 구조 (React 18 + TypeScript + Vite 6, 의존성은 react/react-dom 뿐)**
- `src/api/` — `types.ts`(엔진 반환 타입), `client.ts`(fetch 래퍼, 모든 오류를 ApiError{code,hint,kind} 로), `ws.ts`(useEngineEvents: /ws 자동 재연결)
- `src/state/store.tsx` — AppProvider 하나: health·회차·선택·작업·활성 작업·로그·오류 카드·토스트·tick(데이터 변경 신호). WS 이벤트가 여기서 상태를 갱신한다.
- `src/components/ui.tsx` — Button/Badge/Card/Empty/Progress/Spinner/Toasts/Tabs + fmtTime 류. `src/styles/tokens.css`(디자인 토큰: 다크, 브랜드 노랑 `--accent`), `app.css`(골격·컴포넌트).
- `src/features/` — Header(상태 칩·실행 중 배지·연결 끊김) + Alerts(health.problems 배너), Sidebar(회차 목록·단계 점·등록), Pipeline(단계 선택 그리드·프리셋·실행/취소·진행률·오류 카드·로그 창), Candidates(필터·카드·keep/no), Calibration(점검·미리보기·ROI 편집), Metrics(지표 표 + 작업 이력 → 로그).
- 개발: `npm run dev`(5173, /api·/media·/ws 를 8765 로 프록시). 배포: `npm run build` → `dist/` 를 엔진 `project.ui_dir` 가 자동 서빙(없으면 예전 `ui/`). Node 는 포터블(`C:/Users/jaeye/tools/node`, PATH 에 추가해 사용).
- 다음 화면 작업: 후보 카드 드래그 정렬/비교 보기, ROI 드래그 편집(지금은 수치), 키보드 판정(K/N), 라이브 탭 자리.

**`desktop/` 껍데기 (Electron, 2026-10-18 밤)** — 의존성 electron + ws 뿐, 빌드 도구 없음(플레인 CommonJS 3파일).
- `engine.js`: 엔진 사이드카. 파이썬 탐색(개발: 저장소 `.venv`, 배포: `resources/engine/python.exe`, 환경변수 `CLIPFORGE_ENGINE_PY` 로 덮어씀) → 포트 선택(8765 에 **이미 우리 엔진이 떠 있으면 그대로 붙고**, 아니면 빈 포트) → spawn(stdout/stderr 를 쉘 로그로) → `/api/health` 가 200 될 때까지 대기(최대 60초) → 종료 시 `taskkill /T /F`.
- `main.js`: 창(부팅 화면 → 엔진 URL 로드, 외부 링크는 시스템 브라우저, 닫기 = 트레이로 숨김), 트레이(열기·상태·로그 폴더·브라우저에서 열기·종료), `/ws` 구독으로 진행률을 트레이 메뉴에, 완료/오류를 OS 알림으로. 단일 인스턴스. `--smoke` 는 창+엔진 준비 후 5초 뒤 자동 종료(점검용). 쉘 로그 `%APPDATA%/clipforge/shell.log`.
- `preload.js`: contextIsolation/sandbox 켜고 정보성 값만 노출. 화면은 HTTP/WS 로 엔진과 직접 대화하므로 IPC 가 필요 없다 — **stdio JSON Lines 전송은 다른 껍데기(C#·CLI 자동화)를 위해 유지**하되 Electron 은 쓰지 않는다 (결정: 화면 코드가 브라우저·Electron 에서 동일).
- `package.json` 의 `build` 블록은 electron-builder NSIS 설정 자리(아이콘·extraResources: engine-dist → engine). **남은 것**: electron-builder 로 설치본, 자동 업데이트(electron-updater, 배포 서버 결정 뒤).

**`engine-dist/` 포터블 엔진 런타임 (2026-10-18 밤, `scripts/build_engine_dist.py --smoke`)** — 설치본의 몸통. 관리자 권한·레지스트리·PATH 불필요, 폴더째 옮겨도 동작(상대 경로만).
| 구성 | 내용 | 용량 |
|---|---|---|
| python.exe + `python312._pth` | python.org 임베더블 3.12.10 (`[zip, ., Lib\site-packages, import site]` — PYTHONPATH·사용자 site 무시 → 격리) | 11MB |
| Lib/site-packages | `requirements-runtime.txt`(개발 전용 pytest·httpx 제외) 를 개발 venv 의 pip 로 `--target` 설치 | 2.0GB (그중 NVIDIA cuBLAS/cuDNN 1.9GB) |
| clipforge/ games/ data/ assets/ app/dist/ | 엔진·프로필·사전·폰트·화면. `APP_ROOT` = engine-dist | 5MB |
| bin/ffmpeg.exe, ffprobe.exe | Gyan full 9.0.2 (GPL 고지 동봉). `find_ffmpeg` 가 번들 bin/ 을 PATH 보다 먼저 봄 | 434MB |
| models/faster-whisper-large-v3-turbo | HF 캐시 스냅샷 복사. `transcribe` 가 로컬 폴더 우선 → 오프라인(HF_HUB_OFFLINE 에서 검증), GPU 실패 시 CPU/int8 폴백 | 1.6GB |
| **합계** | | **4.5GB** |
- 검증: 번들 파이썬만으로(PATH=bin) 엔진 기동 → health 전부 OK(ffmpeg·NVENC·GPU·Whisper GPU·OCR·폰트), Electron `CLIPFORGE_ENGINE_DIST=1 --smoke` 통과, ep59 오디오 오프라인 전사 OK.
- `engine-dist/` 는 이제 **설치본에 통째로 들어가지 않는다** — 릴리스 아티팩트(층 A zip + 층 B zip 들)의 원본이자 개발 중 번들 점검용. 설치본에는 그중 코드 경로만 동봉(§9.2).
- 데이터 분리: 껍데기가 설치본에서 `CLIPFORGE_DATA=%APPDATA%/clipforge/data` 를 넘긴다(§6 원칙: 업데이트가 라벨을 지우지 않음).
- 용량 줄일 여지(순서대로): ① CPU 전용 변형(NVIDIA 휠 제외 → 2.6GB, 전사 20배 느림) ② ffmpeg essentials 빌드(≈ 200MB 절약, libass·NVENC 포함 여부 확인 필요) ③ 모델을 설치 후 첫 실행에 내려받기(1.6GB 절약, 오프라인 원칙과 충돌) ④ cuDNN 을 CTranslate2 가 쓰는 서브 라이브러리만 남기기. v1 은 4.5GB 그대로 간다 — 친구 PC 는 4K 녹화 환경이라 디스크가 문제되지 않는다.
- 전사 백엔드는 faster-whisper 하나(CUDA 실패 시 CPU/int8 자동 폴백). 예전 ffmpeg whisper 필터(ggml 모델) 경로는 제거했다 — 번들에 없는 파일을 가리켰고 CPU 폴백과 역할이 겹쳤다. `models/ggml-*.bin` 은 더 이상 쓰지 않는다.

### 9.2 앱 내 업데이트 설계 (2026-10-18 밤) — 재설치 없이, 작은 것만, 승인 뒤 적용

원칙: 설치본 4.5GB 를 매번 다시 받게 하면 아무도 업데이트하지 않는다. **바뀐 층만 받는다.** 그래서 설치본을 세 층으로 나눠 각각 버전을 매긴다.

| 층 | 내용 | 크기 | 바뀌는 빈도 | 적용 방법 |
|---|---|---|---|---|
| **A. 앱 코드** | `engine/clipforge/`, `engine/games/`, `engine/data/`, `engine/app/dist/` (파이썬 코드 + 프로필·사전 + 화면) | 1~5MB zip | 자주 (규칙·화면 수정마다) | 껍데기가 zip 을 받아 해시 검증 → `engine/_staging/` 에 풀기 → 엔진 중지 → 폴더 교체(이전본은 `_prev/` 로 보관, 실패 시 복원) → 엔진 재시작 → 화면 새로고침. **앱 재시작 불필요, 수 초.** |
| **B. 런타임 구성요소** | `python+site-packages`, `bin/ffmpeg`, `models/whisper` — 각각 독립 버전 | 0.4~2GB 씩 | 드묾 (분기에 한 번 이하) | 구성요소 단위로만 받는다(바뀐 것만). 백그라운드 다운로드(재개 가능) → 검증 → 엔진 중지 → 폴더 교체 → 재시작 |
| **C. 껍데기** | Electron 실행 파일 자체 | ~100MB | 아주 드묾 | electron-updater(NSIS, blockmap 차등) — 종료 시 설치. 한 번 깔리면 거의 안 바뀜 |

**매니페스트** (서버의 `channels/stable/latest.json`, 서명 없는 대신 sha256 + HTTPS):
```json
{"published": "2026-10-18T22:00:00+09:00",
 "shell":  {"version": "0.2.0", "min_engine_code": "0.2.0"},
 "engine_code": {"version": "0.2.3", "url": "…/engine-code-0.2.3.zip", "sha256": "…", "size": 3123456, "notes": "득템 배너 reset 규칙 수정"},
 "components": {
   "python":  {"version": "3.12.10+pkg2026.10", "url": "…/python-….zip", "sha256": "…", "size": 2100000000},
   "ffmpeg":  {"version": "9.0.2",  "url": "…", "sha256": "…", "size": 434000000},
   "whisper": {"version": "large-v3-turbo-ct2-1", "url": "…", "sha256": "…", "size": 1600000000}},
 "compat": {"engine_code>=0.3": {"python": ">=3.12.10+pkg2026.10"}}}
```
로컬은 `engine/VERSION.json`(빌드 스크립트가 이미 씀)에 같은 키로 현재 버전을 둔다. 비교는 문자열 동등이 아니라 semver(앱 코드)·명시 버전(구성요소).

**흐름 (껍데기 `updater.js`)**
1. 시작 10초 뒤 + 6시간마다 `latest.json` 을 받는다 (실패는 조용히; 오프라인이면 아무 일도 없음).
2. 차이가 있으면 화면 상단에 한 줄: "업데이트 있음 — 앱 코드 0.2.3 (3MB) · 모델 (1.6GB)". **자동으로 받는 것은 A 층만**(작으므로 백그라운드 다운로드). B 는 사용자가 "받기"를 눌러야 받는다(용량·시간 표시, 재개 가능).
3. 적용은 항상 **사용자 승인**: "지금 적용" 버튼. 단, 작업(Job)이 돌고 있으면 버튼을 비활성화하고 "작업이 끝나면 적용"을 제안(방송 중 끊지 않는다 §2-7).
4. 적용 = 엔진 중지 → 교체 → 재시작 → 화면 reload. 실패하면 `_prev/` 로 되돌리고 알림. 성공하면 `VERSION.json` 갱신, 변경 내역(notes) 토스트.
5. C 층은 electron-updater 기본 흐름(다운로드 완료 → "다음 종료 때 설치"). 강제하지 않는다.

**호환성 규칙**: 매니페스트의 `compat` 로 "이 앱 코드는 이 런타임 이상이 필요"를 선언. 껍데기는 A 를 적용하기 전에 B 가 충족되는지 보고, 아니면 B 를 먼저 받게 안내한다. 데이터 스키마는 §10-8 의 `schema.py` 가 메모리 마이그레이션으로 처리하므로 A 업데이트가 라벨·캐시를 깨지 않는다(새 버전이 더 높은 schema 를 쓰면 이전 앱은 E_SCHEMA_NEWER 로 거부 — 롤백 시 캐시만 재생성).

**서버 (결정 필요)**: 정적 HTTPS 폴더면 충분하다 — `latest.json` + zip 들. 후보:
- GitHub Releases: 무료, 간단. **단일 파일 2GB 제한**이라 설치본 4.5GB 는 못 올리고(설치본은 다른 곳), 구성요소 zip 은 전부 2GB 미만이라 가능(python 층은 cublas/cudnn 을 나누면 안전). electron-updater 의 GitHub provider 가 C 층을 바로 지원.
- Cloudflare R2 / S3 + 정적 호스팅: 용량 제한 없음, 다운로드 속도 좋음, 소액 비용. electron-updater `generic` provider.
- 추천: **R2 하나로 통일**(설치본·구성요소·매니페스트 모두). 친구 한 명 배포 규모에선 비용이 거의 0.
서명: 코드 서명 인증서가 없는 동안은 SmartScreen 경고를 피할 수 없다(설치본 첫 실행 때 "추가 정보 → 실행"). 앱 내 업데이트(A·B 층)는 zip 교체라 SmartScreen 과 무관 — **재설치를 피하는 또 하나의 이유**.

**설치본은 작게, 대용량은 첫 실행 때 (2026-10-18 밤 결정, 사용자 제안)**: 4.5GB 설치본은 만들지 않는다. 설치본 = Electron + 엔진 코드(층 A, 5MB) + 7za.exe ≈ 100MB. 첫 실행 때 껍데기가 `latest.json` 을 읽어 **구성요소 선택 화면**(python-base 193MB · cuda 1.4GB[선택, NVIDIA 감지 시 기본 켬] · ffmpeg 182MB · whisper 1.5GB)을 보여주고, 받은 것을 `%LOCALAPPDATA%\clipforge\runtime\` 에 풀어 엔진을 띄운다. 첫 설치와 업데이트가 **같은 코드**(`desktop/components.js`)다. 장점: 설치본이 작고, GitHub 2GB 제한 안에 들어가고, CPU 전용 설치가 되고, 런타임이 사용자 폴더라 업데이트에 UAC 가 없다. 단점: 오프라인 첫 설치 불가 → USB 배포는 릴리스 폴더를 통째로 복사하고 `%LOCALAPPDATA%\clipforge\update-url.txt` 에 `file:///E:/...` 를 적는 것으로 해결(또는 `CLIPFORGE_UPDATE_URL`).

**호스팅 결정 (2026-10-18 밤): GitHub Releases, 저장소 `jaeyeonling/clipforge`, 일단 private.**
- 두 종류의 릴리스: 앱 `v<ver>`(Setup.exe · blockmap · latest.yml · engine-code zip · latest.json) 와 런타임 `runtime-YYYY.MM`(구성요소 zip 4개, 각 2GB 미만). latest.json 은 `releases/latest/download/latest.json` 으로 항상 최신 앱 릴리스를 가리키고, 그 안의 구성요소 URL 은 런타임 릴리스의 절대 URL.
- **private 의 대가**: 릴리스 자산을 토큰 없이 못 받는다. 앱은 `%LOCALAPPDATA%\clipforge\github-token.txt`(또는 `CLIPFORGE_GH_TOKEN`)의 fine-grained PAT(저장소 clipforge, Contents read-only)로 API 를 거쳐 받는다(`components.js resolveAsset`: 릴리스 조회 → 자산 API URL → `Accept: application/octet-stream`, S3 리다이렉트 시 Authorization 제거). electron-updater 는 `setFeedURL({private:true, token})`. 친구 PC 에 토큰 파일 하나를 놓아 주는 운영 부담이 있고, 토큰이 새면 저장소 읽기가 가능하므로 **공개 전환 시점에 토큰 발급을 취소**한다. public 으로 바꾸면 토큰 없이 그대로 동작(`CLIPFORGE_GH_PRIVATE=0` 또는 release.config.js).
- 배포 명령: `python scripts/publish_github.py runtime`(처음 한 번·런타임 갱신 시) → `python scripts/publish_github.py app`(화면 빌드 → 엔진 코드 zip·latest.json → NSIS → gh release create). gh CLI 는 포터블(`C:/Users/jaeye/tools/gh`), `gh auth login` 은 사용자가 한 번.
- 껍데기(층 C): electron-updater, 자동 다운로드 + 종료 시 설치(강제 재시작 없음), 트레이 "앱 X 설치하고 다시 시작". 코드 서명이 없어 electron-updater 의 서명 검증은 건너뛴다(publisherName 미설정).

**구현 상태**: ✅ (1) `scripts/build_engine_dist.py --release DIR --release-components` : engine-code zip + 구성요소 zip(python-base/cuda/ffmpeg/whisper) + latest.json(sha256·size·label·optional) ✅ (2) `desktop/components.js` : fetchManifest(https/file) · present(파일로 설치 판정) · plan(missing/update) · download(이어받기·sha256) · install(7za → `_staging` → 경로 교체, 실패 시 `_prev` 복원; python-base 교체 시 cuda 폴더 보존) · seedFromResources(동봉 엔진 코드 심기) ✅ (2') `desktop/main.js` : 첫 실행 설치 화면(IPC), 10초 뒤·6시간마다 확인 → 알림 + 트레이 "업데이트 적용"(작업 중이면 비활성) → 엔진 중지·교체·재시작 · ⬜ (3) React 화면의 업데이트 배너/카드 (지금은 트레이·알림) · ✅ (4) electron-updater 로 C 층(`main.js setupShellUpdater`) · ✅ 호스팅 = GitHub private(위) · ⬜ 저장소 생성·첫 릴리스 업로드(gh auth 뒤).

### 9.3 화면 결 (2026-10-20): 토스 철학
사용자 요청으로 토스의 원칙을 따른다 — **한 화면 한 가지 일·버튼 하나**(실행 탭 히어로 + `.btn.cta`), **테두리 대신 면과 여백**(1px 테두리 없음, 배경 톤 3단계, 10/14/20px 모서리), **큰 숫자**(진행률 `.bigpct`, 기록 `.stat`), **바텀 시트**(안 쓰는 이유·업데이트 재시작 묻기 `.sheet`), **말하듯 쓰기**('~해요'체, 다음 행동을 문장으로 먼저). 색은 토스 다크 팔레트(`tokens.css`: 중성 회색 면, 파란 주요 버튼 #3182f6), 브랜드 노랑은 `--brand` 로 워드마크·순위에만. 설명 문장은 `app/src/api/tips.ts` 에 모으고 요소에는 `data-tip` 만 붙인다(App.tsx `useTooltips` 가 body 고정 박스 하나를 옮겨 띄움). 헤더의 환경 칩 7개는 상태 칩 하나로 줄이고 자세한 건 설정 탭.

## 10. 지금 코드에서 바꿔야 할 것 (리팩터링 목록, 우선순위 순)

진행 (2026-10-18 밤): ✅ 1 설정 객체(`project.py`: 앱/데이터 폴더 분리, ffmpeg 자동 탐색, health 진단) · ✅ 2 Job 러너(`jobs.py`: 단계 큐, 진행률[prep 는 프레임 수 폴링, export 는 클립 단위], 취소, 작업 로그 파일, 오류 코드+힌트) · ✅ 3 API(`api/methods.py` 전송 무관, `api/server.py` HTTP+WebSocket+미디어 Range, `api/stdio.py` JSON Lines) · ✅ 4 판정 I/O(`decision.set` → labels.csv) · ◐ UI v0(`ui/`: 빌드 없는 로컬 웹 화면 — 회차·실행·후보 리뷰·판정·지표). **UI 스택 결정**: 1차는 엔진이 직접 서빙하는 로컬 웹 UI. 데스크톱 껍데기(Tauri/WPF)는 stdio 또는 HTTP 로 같은 API 를 쓴다. ✅ 5 캘리브레이션(`calibrate.py`: 배너 OCR·패널 제목·채팅·HUD 적중률 점검 + ROI 박스 미리보기 + ROI 수치 편집/프로필 저장, UI 패널) · ✅ 7 테스트 뼈대(`tests/`: pytest 17개 — timeline/adapters/candidates/배너 전이/lexicon/weaklabel/subtitles/textdraw/발화 경계/채팅 교정 + API: Engine·HTTP·판정·프로필 검증). ✅ 6 오류·로그(`errors.py`: 모든 예외 → {code, message, hint, kind=user|internal}, 단계 전제조건은 EngineError 로 명시[E_NO_PREP/E_NO_SHORTS/…]; Job 은 끝날 때 run 매니페스트(reports/jobs/<id>.manifest.json: 파라미터·단계별 소요·오류·엔진/스키마 버전)를 쓰고 재시작 후에도 job.list 가 이력을 보여줌; `job.log` 메서드/`/api/jobs/{id}/log`; HTTP 오류는 검증 실패·미처리 예외까지 전부 {"error":{…}} 한 형태(404=E_NOT_FOUND, 400=사용자 오류, 500=내부); reports/engine.log 회전 로그; UI: 상단 문제 배너(health.problems), 오류 카드(코드·힌트·같은 설정으로 다시 실행·로그 보기), 레벨별 색 로그+오류만 필터, 작업 이력 클릭→로그, WS 끊김 표시) · ✅ 8 스키마 버전(`schema.py`: project.json(데이터 루트)·meta·shorts·index·게임 프로필에 schema_version, v0(키 없음/맨 리스트)→v1 마이그레이션은 메모리에서, 엔진보다 새 파일은 E_SCHEMA_NEWER 로 거부하고 job.run 차단; labels.csv 는 열 구조가 스키마라 project.json 의 labels_schema 로 관리). **§10 리팩터링 8개 전부 완료 → 로드맵 1단계(엔진화) 닫힘.** ep59 캘리브레이션 결과: 배너 68% / 패널 40% / 채팅 92% / HUD 99% → 전부 pass.


1. **설정 객체**: `ROOT/CACHE/REVIEW` 전역과 PATH 환경 의존 제거 → `Project` 객체(경로·프로필·도구 위치) 주입. ffmpeg/모델/폰트는 설치 폴더 기준으로 탐색.
2. **Job 러너**: 단계 함수들을 `run_pipeline(episode, stages, progress_cb, cancel_token)` 으로 묶고 ffmpeg 진행률(`-progress pipe`) 파싱.
3. **RPC 서버**: `python -m clipforge.api` — stdio JSON Lines, §4 메서드. CLI 는 RPC 의 얇은 래퍼로 재구성.
4. **판정 I/O**: keep/no 폴더 대신 `decision.set` → labels.csv (폴더 흐름은 호환 유지).
5. **캘리브레이션**: ROI 박스 미리보기 + 적중률 점검 + ROI 드래그 저장.
6. **오류·로그**: 예외 → 코드+힌트, 로그 파일, run 매니페스트.
7. **테스트 뼈대**: pytest + ep59 골든 픽스처 + 합성 스모크.
8. **스키마 버전**: meta/labels/shorts JSON 에 version 필드, 마이그레이션 자리.
그 다음 껍데기(Electron) → 라이브 모듈 순.

## 11. 단계 로드맵

| 단계 | 산출물 | 완료 기준 |
|---|---|---|
| 0. 검증 | 편집본 5~10편에서 현재 파이프라인 지표 | hit@3 ≥ 0.8, 거절 상위3 ≤ 1 (라벨 30개+) |
| 1. 엔진화 | §10 의 1~8 | `run` 한 번에 끝, RPC 로 UI 없이도 호출 가능, 테스트 통과 |
| 2. UI v1 | 회차 추가 → 실행 → 리뷰(재생·판정) → 내보내기 — **구현됨(2026-10-19~20)**: 온보딩(시작 화면·'다음' 진행 띠·도움말 탭), 한 버튼 실행, 토스 결 UI(§9.3), 툴팁 설명, '~해요' 문구, 오른쪽 클릭 복사 | 친구가 설명 없이 한 회차 처리 (실사용 확인 전) |
| 3. Premiere 검증 | XML 임포트·세로 시퀀스·SRT 캡션 | 친구 Premiere 에서 실사용 1회 |
| 4. 라이브 v1 | 득템 배너 자동 갱신(승인 모드) + 북마크 — **구현됨(2026-10-19, docs/design/LIVE.md)**: 바닥 아이템 라벨 감지(세트·유니크, CPU) → 제안 카드 승인 → 배너 텍스트·OBS 소스 갱신, 북마크(단축키·채팅 폭주·승인), 녹화 타임코드. 실방송 검증은 친구 PC 에서 | 방송 1회 무사고, 오탐 0 |
| 5. Phase 2 | 원본 VOD → 편집 포인트 — **파이프라인 구현됨(2026-10-19)**: 회차 종류 original, 원본용 신호 세트(common.yaml pipelines), 배너 OCR 변화 감지 모드, 단계 candidates/align/eval, 편집 포인트 탭(원본 재생·kept/no). 실측은 원본 VOD 입수 뒤 | recall ≥ 0.95, coverage ≤ 10% |
| 6. 배포 | 설치본·업데이트·고지 — 구현됨: 슬림 NSIS + 첫 실행 구성요소 다운로드, 앱 내 업데이트(배너 + '새 버전이 준비됐어요' 시트, 작업 중 잠금), USB 오프라인 묶음. 남은 것: `gh auth login` 뒤 첫 릴리스 업로드, 깨끗한 PC 실제 설치, 코드 서명(SmartScreen) | 깨끗한 PC 설치 성공 |

## 12. 결정 요청

1. **라이브 기능의 우선순위**: 득템 배너 자동 갱신이 친구에게 실제로 가치가 있는가? (지금 메모장 수동 입력) — 있다면 v1 에 넣고, 아니면 포스트 전용으로 먼저 간다.
2. ~~UI 스택~~ **결정(2026-10-18)**: 웹앱 기반 + 데스크톱 완성도(OP.GG 데스크톱 방식) → Electron + React. §9.1.
3. **대상 범위**: 친구 한 명 전용(프로필 1개) vs 처음부터 멀티 스트리머 구조. 구조는 멀티로 준비하되 v1 은 1명 — 이 가정으로 진행해도 되는가.
4. **플랫폼 채팅 연동**: 채팅 오버레이 OCR 대신 치지직/SOOP API 로 채팅을 직접 받을지 (정확하지만 인증·약관 확인 필요).
5. **Phase 0 데이터**: 유튜브 공개본 다운로드로 5~10편을 지금 확보할지 (화질은 OCR·전사에 충분, 원본 오면 교체).
