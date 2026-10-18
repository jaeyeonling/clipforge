# 라이브 모듈 v1 — 방송 중 득템 배너 제안 · 북마크 · OBS 연동 (2026-10-19)

> PRODUCT_ARCHITECTURE §7 의 구현. 원칙: **방송을 방해하지 않는다**(GPU 금지, 1 fps, 실패는 조용히), **오탐이 방송에 그대로 나가지 않는다**(승인 모드 기본).
> 친구의 라이브 환경(OBS·플랫폼)이 이 PC 에 없어 **녹화 프레임 재생**으로 개발·검증했다. 실방송 검증 항목은 §6.

## 1. 무엇을 하나

| 기능 | 입력 | 출력 |
|---|---|---|
| 득템 배너 제안 | 게임 화면의 바닥 아이템 라벨(세트 초록 · 유니크 금색 · 옵션 희귀 노랑) | 제안 카드 "카이트 쉴드 (set) — 배너에 추가?" → 승인 시 배너 텍스트에 추가 + OBS 텍스트 소스 갱신 + 북마크 |
| 북마크 | 단축키(앱 전역 Ctrl+Alt+M)·버튼·채팅 활동 폭주 | `live/<세션>/bookmarks.json` {t_wall, t_rec(OBS 녹화 타임코드), kind, note} → 방송 후 Phase 2 의 앵커 |
| 배너 관리 | 현재 배너 항목 편집 | `banner.txt` + OBS `SetInputSettings` |
| 리플레이 | 승인 시 옵션 | OBS `SaveReplayBuffer` |

## 2. 왜 바닥 라벨인가
D2R 은 Alt 를 누르거나 커서를 올릴 때 바닥 아이템 이름을 **등급색 글자 + 검은 상자**로 띄운다. 방송에서 "템을 보여주는 순간" = 라벨이 뜬 순간이고, 등급색이 곧 가치의 1차 필터다(세트·유니크만 제안). 인벤토리 안 툴팁은 라벨보다 복잡하고, 배너 OCR(기존 item_banner)은 친구가 이미 손으로 적은 뒤라 늦다.

## 3. 감지 파이프라인 (CPU, 프레임당 ~150ms + OCR 0.1~0.4s/라벨)
```
프레임(1 fps, ≤1920 폭으로 축소) ─ 게임 영역(배너·HUD 제외 7%~86%) ─ 등급별 RGB 마스크
  ─ 4px 격자 연결 성분 ─ 같은 줄 상자 병합(단어 띄어쓰기) ─ 모양 필터(h 14~48, w ≥ 1.6h) ─ 상자 내부 = 어두운 배경 + 등급색만(중간톤 ≤ 35%)
  ─ rec-only OCR(검출 생략, 6px 여백, 3배 확대) ─ 점수 ≥ 0.6 ─ 사전(lexicon) 정규화 ─ 같은 이름 90초 쿨다운 ─ 제안
```
- 마스크 값은 ep59 1080p JPEG 에서 쟀다. 세트 초록 텍스트 중앙값 (100,172,95), 금색 UI 테두리·불꽃은 "중간톤 비율" 필터로 떨어진다.
- 희귀(노랑)은 기본 끔: 바닥에 흔하고 방송 가치가 낮다. 설정에서 켤 수 있다.
- OCR 은 det 을 건너뛴다: 상자가 이미 한 줄이라 det 이 단어 일부를 놓쳤다(`카이트` vs `카이트쉴드`).

검증(ep59 프레임): 라벨이 있는 150~180초 구간에서 세트 `카이트쉴드` 0.99 로 읽고, 라벨 없는 무작위 프레임 7장에서 오탐 0 (UI 테두리 2건은 중간톤 필터가 제거).

## 4. 구성요소
- `live/source.py` — ScreenSource(PIL ImageGrab, 영역/전체) · FramesDirSource(캐시 프레임, 개발) · VideoFileSource(ffmpeg 파이프, 리플레이 테스트) · (후속) ObsSource(GetSourceScreenshot)
- `live/detect.py` — drop_labels, LabelOCR(rec-only RapidOCR + lexicon), chat_activity
- `live/obs.py` — obs-websocket v5: Hello/Identify(SHA256 challenge) · SetInputSettings · GetInputSettings · GetRecordStatus · SaveReplayBuffer · GetInputList
- `live/session.py` — 스레드 루프, 제안(승인/무시), 북마크, 배너, 파일 기록(events.jsonl·bookmarks.json·suggestions.json·banner.txt), UI 이벤트
- 엔진 API `live.*` (status/start/stop/mark/approve/dismiss/banner/obs.inputs) · WS 이벤트 `{"type":"live", "event":{…}}` · 앱 "라이브" 탭 · Electron 전역 단축키

## 5. 안전장치
- 승인 모드 기본 ON. 끄면 제안이 바로 배너로 간다(친구가 신뢰한 뒤 선택).
- OBS 연결 실패·텍스트 갱신 실패는 경고 이벤트만 내고 감지·북마크는 계속.
- 캡처 실패는 다음 주기에 재시도. 소스가 끝나면(파일) 조용히 종료.
- GPU 사용 없음: RapidOCR 은 ONNX CPU, 마스크는 numpy.

## 6. 실방송에서 확인할 것 (친구 PC)
- 4K 화면 캡처 1장/초의 CPU 비용(ImageGrab 은 GDI 복사 — 보통 10~30ms). 게임 창 가림·전체화면 모드에서 잡히는지 → 안 되면 ObsSource.
- 친구 OBS 의 텍스트 소스 이름·배너 포맷("득템 : a,b,★★★c★★★"). 별표 강조는 사람이 넣는 것으로 두고 자동 추가는 이름만.
- 유니크 금색 임계값(방송 캡처는 JPEG 가 아니라 더 선명). 희귀 켤지.
- 채팅 폭주 임계 0.12 가 과하게 울리는지(쿨다운 20초).
- 녹화 타임코드가 OBS `GetRecordStatus.outputDuration` 과 VOD 시각과 맞는지(방송 후 Phase 2 앵커로 쓸 때 기준).
