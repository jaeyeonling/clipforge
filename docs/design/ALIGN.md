# align — 친구 최종본 ↔ 원본 VOD 자동 정렬로 Phase 2 정답 만들기 (v1, 2026-10-19)

> Phase 2 = 원본 녹화(2~7시간) → 편집 포인트. 정답은 "원본의 어느 구간이 친구 최종본(11분)에 살아남았나"다.
> 사람이 7시간을 보며 적으면 하루가 걸리지만, 최종본은 원본의 **오디오를 거의 그대로** 담고 있으므로 소리로 되찾을 수 있다.
> 이 문서는 그 모듈(`clipforge/align.py`)의 설계·파라미터·검증 기준이다. ARCHITECTURE.md §`align` 의 방법 A 를 구체화한 것.

## 1. 입력과 출력

| | 내용 |
|---|---|
| 입력 | 원본 회차 `cache/<orig>/audio.wav` (prep 산출물, 16kHz mono) · 최종본 영상 파일(또는 등록된 회차 id) |
| 출력 | `labels/<orig>.csv` 에 `label=kept, note=auto align …` 행(원본 시각 기준) · `cache/<orig>/align.json`(구간·투표수·신뢰도·미매칭 구간) · `cache/<orig>/fingerprint.npz`(원본 지문 캐시) |
| 소비자 | `eval`(Phase 2 recall/coverage), 후보 가중치 학습, Premiere 리뷰 XML 의 "실제 채택" 트랙(후속) |

실데이터 현황(2026-10-19): 원본 VOD 는 아직 없다(Downloads 의 "원본"은 편집본과 같은 파일). 그래서 **합성 검증**(§5)으로 먼저 만들고, 원본이 오면 §6 의 실측 항목을 채운다.

## 2. 왜 오디오 지문인가

- 친구 편집은 **컷만** 한다(인트로 타이틀·설명 카드 추가, 음량 마스터링, 속도 변경 없음 — ARCHITECTURE 8절 관측). 소리의 스펙트럼 피크 패턴은 재인코딩·볼륨 변화·BGM 일부 추가에도 유지된다.
- 프레임 해시(방법 B)는 게임 화면이 비슷한 장면이 많아 오탐이 잦고, 4K 7시간 디코딩이 30분이다. 오디오는 7시간이 400MB WAV 로 끝난다.
- 편집본의 음량은 마스터링돼 다이내믹 레인지가 좁다(−21 dBFS 중앙값). 절대 크기를 쓰는 방법(RMS 상관)은 깨지고, **국소 최대점(피크)의 상대 배치**만 쓰는 랜드마크 방식은 영향을 안 받는다.

## 3. 알고리즘 (Shazam 식 랜드마크, numpy 만 사용)

```
wav 16k ─ STFT(n_fft 1024 · hop 256 = 16ms) ─ log|X| 0~5kHz(320 bin) ─ 국소 최대(±160ms × ±15bin, 분리 max 필터)
     ─ 1초마다 상위 K=20 개만 남김 ─ 앵커마다 뒤따르는 6개 피크와 쌍 → 해시 (f1·f2·Δt, 24bit)
원본: (hash, t) 를 hash 로 정렬해 저장 ─── 최종본: 같은 방식으로 해시 → searchsorted 로 원본의 모든 (t_orig) 조회
     ─ 쌍 (t_final, t_orig) ─ 창(3초, 0.5초 걸음)마다 offset = t_orig − t_final 투표 ─ 최다 득표 offset
     ─ 득표 ≥ 8 이고 2위의 1.5배 이상이면 채택 ─ 같은 offset(±64ms) 인 연속 창을 구간으로 병합
     ─ 구간 안의 실제 매칭 쌍으로 경계를 다듬음 ─ 1초 미만 버림 ─ labels/<orig>.csv 로
```

핵심 결정
- **창 투표**: Shazam 은 곡 전체가 한 offset 이지만 우리 최종본은 수십 개 구간이 각각 다른 offset 이다. 그래서 3초 창마다 따로 투표한다. 창 3초는 친구의 평균 컷 간격 10초·최소 1~5초보다 짧아 경계가 뭉개지지 않고, 피크 ~60개가 들어 투표가 안정적이다.
- **흔한 해시 제거**: 원본에서 200번 넘게 나오는 해시(무음·게임 루프음)는 버린다. 투표를 오염시킨다.
- **경계 다듬기**: 창 걸음 0.5초가 그대로 경계가 되면 ±0.5초 오차. 구간에 속한 쌍들의 `t_final` 최소/최대로 경계를 당겨 오차를 ~0.1초로 줄인다.
- **미매칭 = 정보**: 매칭이 없는 최종본 구간은 인트로·설명 카드·BGM 교체 구간이다. align.json 에 `unmatched` 로 남겨 Premiere 추가물 통계로 쓴다(ARCHITECTURE 8절 "원본에 없는 구간은 버려야 함").

파라미터(`align.Params`): `n_fft=1024, hop=256, fmax_bin=320, peak_dt=10, peak_df=15, peaks_per_sec=20, fanout=6, max_pair_dt=64(=1s), max_pair_df=96, common_hash_cap=200, win_s=3.0, step_s=0.5, min_votes=8, margin=1.5, join_tol_frames=4, min_seg_s=1.0`.

## 4. 성능 예산

| 단계 | 7시간 원본 | 11분 최종본 |
|---|---|---|
| WAV 읽기 | 400MB, 수 초 | 22MB |
| STFT(120초 청크) | 1.58M 프레임, numpy rfft ~20초 | 1초 |
| 피크·해시 | 피크 ~500k, 해시 ~3M, 정렬 수 초 | 해시 ~30k |
| 조회·투표 | 창 1,400개 × unique/counts | ~수 초 |
| 합계 | **2~3분**, 메모리 < 1GB (청크 처리, 피크만 보관) | |

원본 지문은 `fingerprint.npz` 로 캐시해 두 번째 최종본(쇼츠·몰아보기)부터는 조회만 한다.

**실측(2026-10-19, ep59 11.7분 오디오)**: 지문 1.7초, 피크 15.5/s, 해시 86/s, 반복 최대 8회(공통 해시 컷 200 에 걸리는 것 없음). 7시간 환산 **약 1분, 해시 2.2M = 26MB** — 예산보다 훨씬 작다. 합성 검증 결과는 §5 끝.

## 5. 검증 (합성) — `tests/test_align.py`

1. **합성 신호**: 90초 "원본"(120ms 마다 무작위 4음 + 잡음) → "최종본" = 2초 무음 인트로 + 원본[10,22) + 2초 잡음 카드 + 원본[40,49) + 원본[70,85), 게인 0.6, 잡음 추가. 기대: 구간 3개, 경계 오차 ≤ 0.25초, offset 정확, 인트로·카드는 미매칭.
2. **실오디오**(ep59 `audio.wav` 가 있을 때만): 편집본에서 4구간을 잘라 이어 붙이고 ffmpeg aac 64kbps 로 재인코딩한 뒤 되돌려 정렬. 기대: 4구간 전부, 경계 오차 ≤ 0.3초. 재인코딩·게인 변화 내성 확인.
3. 지표: recall(원본 기준 살아남은 구간을 얼마나 찾았나), 경계 오차 중앙값, 오탐(없어야 함).

결과(2026-10-19, `tests/test_align.py` 3개 통과): 합성 3구간 전부 회수·경계 오차 ≤ 0.25s·인트로/카드 미매칭 정확. 실오디오 4구간(6초짜리 포함, AAC 64kbps 재인코딩) 전부 회수·경계 오차 ≤ 0.35s·오탐 0. 경계는 창 단위가 아니라 **매칭 쌍이 0.5초에 3개 이상 밀집한 첫/마지막 시각**으로 잡는다(우연히 맞는 쌍 하나가 경계를 끌고 가던 문제를 고침).

## 6. 원본이 오면 확인할 것

- 친구 Premiere 출력의 음량 마스터링이 피크 배치를 얼마나 바꾸는지(창당 득표 분포). min_votes 재조정.
- 설명 카드 구간의 BGM 유무. BGM 이 원본 소리 위에 겹치면 득표가 줄지만 보통 통과.
- 같은 효과음이 반복되는 D2R 특성(아이템 드랍음·스킬음)으로 생기는 **다중 후보 offset** — margin 1.5 로 거르는지, 못 거르면 창을 4초로.
- 7시간 실측 시간·메모리. 예산(§4)을 넘으면 hop 384.

## 7. 이후 (이 모듈 위에 쌓는 것) — 2026-10-19 구현 상태

- ✅ 앱 통합: 회차를 `original` 로 등록하면 기본 단계가 prep → transcribe → signals → candidates → align → eval. 파이프라인 탭에서 최종본 파일을 고르면 align 이 돈다(파일 없으면 E_BAD_PARAMS).
- ✅ 원본용 신호 세트(`games/common.yaml pipelines.original`): audio_loudness · frame_motion · item_banner(변화 감지 모드) · chat_burst · speech_keyword · ui_state. chat_text(채팅 OCR)·cut_density·edit_emphasis 는 편집본 전용. scdet 끔.
- ✅ item_banner 변화 감지: 64×12 회색 썸네일의 평균 절대차 > 6 이면 새 구간, 구간당 1회 OCR. 7시간에 수십 회 호출(기존 coarse 방식은 8,400회).
- ✅ `eval`: labels/<id>.csv(kept, no 제외) × candidates.json → recall/precision/coverage, reports/<id>_editpoints_eval.json.
- ✅ 편집 포인트 탭: 원본 재생(`/media/video/<id>`, Range), 후보 목록(정답 겹침 표시·필터), 키보드 판정(kept/no → labels 의 `ui` 행, auto align 행과 공존).
- ✅ 라벨 범주 붙이기(2026-10-19): 범주는 `games/common.yaml label_categories`(drop·reaction·fail·talk·chat·misc, 단축키 1~6, 색). 편집 포인트 탭의 "정답 구간" 카드에서 칩 클릭/숫자키로 붙이고, CSV 의 label 열이 `kept` → 범주 key 로 바뀐다. `evaluate` 가 label 별로 집계하므로 **범주별 recall** 이 바로 나온다(어떤 신호를 보강할지 알려주는 표). 최종본이 없을 때는 플레이어에서 I/O 로 구간을 찍어 직접 추가(`manual` 행). API: kept list/set/add/delete.
- ⬜ 친구 쇼츠 역매핑 · ⬜ 원본 VOD 실측(§6).

ep59(편집본)를 원본처럼 돌린 점검: 후보 11개(임계 1.5), 합성 최종본 3구간 align 93% 매칭, recall 100% / coverage 38%. coverage 가 큰 건 편집본이라 전부 '재미있는' 구간이기 때문 — 원본에서의 수치는 아직 없다.

- `eval`(Phase 2): labels `kept` vs `candidates.json` → recall / coverage. 목표 recall ≥ 0.95, coverage ≤ 10%.
- 라벨 범주 붙이기: 자동 구간에 사람이 drop/reaction/fail 만 붙이면 된다(30분 → 10분).
- 쇼츠 역매핑: 친구가 올린 쇼츠도 같은 모듈로 편집본·원본에 매핑 → Phase 1 정답이 공짜로 늘어난다.
