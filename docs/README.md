# 문서

| 읽는 사람 | 문서 | 내용 |
|---|---|---|
| 쓰는 사람 | [USER_GUIDE.md](USER_GUIDE.md) | 설치 · 첫 실행 · 쇼츠 초안 · 자막 · 업데이트 · 문제 해결 (한 장) |
| 개발하는 사람 | [DEVELOPMENT.md](DEVELOPMENT.md) | 준비 · 실행 · 테스트 · CLI 실험 하네스 · 신호 추가 · 배포 명령 |
| | [ARCHITECTURE.md](ARCHITECTURE.md) | 프로세스 구조 · 엔진 모듈 · 파이프라인 · API · 데이터 폴더 · 배포와 업데이트 · 품질 |
| | [ENGINE.md](ENGINE.md) | 분석 코어: 신호 · 쇼츠 후보와 점수 · 판정 학습 · 렌더 · 편집 포인트 · 평가 |
| | [GAME_PROFILE.md](GAME_PROFILE.md) | 다른 게임 추가하기: 프로필 · 화면 영역 · 어휘 · 신호 묶음 |
| | [CODE_SIGNING.md](CODE_SIGNING.md) | 설치본 코드 서명: 인증서 고르기 · 설정 · 릴리스 확인 · 게시자 바꾸기 |
| | [../CONTRIBUTING.md](../CONTRIBUTING.md) | 코드 규칙 · 올리기 전 검사 · 문구 규칙 |

## 설계 문서 (기능 하나를 깊게)

| 문서 | 내용 |
|---|---|
| [design/ALIGN.md](design/ALIGN.md) | 편집본·쇼츠를 원본에 오디오 지문으로 맞춰 정답을 만드는 방법과 검증 |
| [design/LIVE.md](design/LIVE.md) | 방송 중 득템 배너 도우미: 감지 · 승인 · OBS 연동 · 안전장치 |
| [design/SHORTS_LAYOUT.md](design/SHORTS_LAYOUT.md) | 세로 초안 레이아웃 후보와 확정 포맷 |

## 설계 노트와 조사 (시간순 기록)

결정이 내려진 순서와 그때의 근거·실측을 그대로 남긴 문서예요. 일부 계획은 이후에 바뀌었어요. 지금의 구조는 위 문서가 기준이에요.

| 문서 | 내용 |
|---|---|
| [notes/ENGINE_LOG.md](notes/ENGINE_LOG.md) | 분석 코어: 참고 레포 조사, 실제 편집본에서 본 것, 신호·점수 규칙이 바뀐 이유 |
| [notes/PRODUCT_LOG.md](notes/PRODUCT_LOG.md) | 제품: 껍데기 선택(Electron), 앱 내 업데이트 설계, 호스팅, 리팩터링 기록 |
| [notes/PERSONA_REVIEW.md](notes/PERSONA_REVIEW.md) | 설치부터 라이브까지 사람의 동선으로 막히는 곳을 찾은 점검 |
| [research/shorts_formula.md](research/shorts_formula.md) | 게임 득템 쇼츠 공식 조사 (길이 · 훅 · 구조 · 자막) |
