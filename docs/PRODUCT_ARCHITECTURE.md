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
| 2. UI v1 | 회차 추가 → 실행 → 리뷰(재생·판정) → 내보내기 | 친구가 설명 없이 한 회차 처리 |
| 3. Premiere 검증 | XML 임포트·세로 시퀀스·SRT 캡션 | 친구 Premiere 에서 실사용 1회 |
| 4. 라이브 v1 | 득템 배너 자동 갱신(승인 모드) + 북마크 | 방송 1회 무사고, 오탐 0 |
| 5. Phase 2 | 원본 VOD → 편집 포인트 | recall ≥ 0.95, coverage ≤ 10% |
| 6. 배포 | 설치본·업데이트·고지 | 깨끗한 PC 설치 성공 |

## 12. 결정 요청

1. **라이브 기능의 우선순위**: 득템 배너 자동 갱신이 친구에게 실제로 가치가 있는가? (지금 메모장 수동 입력) — 있다면 v1 에 넣고, 아니면 포스트 전용으로 먼저 간다.
2. ~~UI 스택~~ **결정(2026-10-18)**: 웹앱 기반 + 데스크톱 완성도(OP.GG 데스크톱 방식) → Electron + React. §9.1.
3. **대상 범위**: 친구 한 명 전용(프로필 1개) vs 처음부터 멀티 스트리머 구조. 구조는 멀티로 준비하되 v1 은 1명 — 이 가정으로 진행해도 되는가.
4. **플랫폼 채팅 연동**: 채팅 오버레이 OCR 대신 치지직/SOOP API 로 채팅을 직접 받을지 (정확하지만 인증·약관 확인 필요).
5. **Phase 0 데이터**: 유튜브 공개본 다운로드로 5~10편을 지금 확보할지 (화질은 OCR·전사에 충분, 원본 오면 교체).
