# 기여 안내

관심 가져 주셔서 고마워요. 버그 제보, 다른 게임 프로필, 신호 아이디어 모두 환영해요.

## 시작하기

준비와 실행 방법은 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) 에 있어요. Windows 10/11, Python 3.12, Node 22, FFmpeg 가 필요해요.

## 올리기 전에

CI 와 같은 검사를 한 번에 돌려요. `-Fix` 를 붙이면 포맷과 자동 수정을 먼저 해요.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -Fix
```

| 영역 | 포맷 | lint | 테스트 |
|---|---|---|---|
| 엔진 `clipforge/` | `ruff format` | `ruff check` | `pytest` |
| 화면 `app/` | Prettier | ESLint (typescript-eslint, react-hooks) | Vitest |
| 데스크톱 `desktop/` | Prettier | ESLint | `node --test` |

규칙은 `pyproject.toml`, `.prettierrc.json`, 각 폴더의 `eslint.config.js` 에 있어요. 예외를 둔 규칙에는 이유를 적어 뒀어요.

## 코드 규칙

- **엔진**: 단계는 `clipforge/jobs.py` 의 `JobRunner` 에, 신호는 `clipforge/signals/` 플러그인으로 넣어요. 사용자에게 보일 오류는 `EngineError(code, message, hint)` 로 던지면 화면이 원인과 할 일을 보여줘요.
- **화면**: 규칙(어떤 단계를 돌릴지 등)은 컴포넌트 밖 순수 함수로 두고 테스트해요 (`app/src/api/plan.ts` 참고).
- **데스크톱**: 패키징에 들어가는 파일은 `electron-builder.config.js` 의 `files` 에 있어야 해요. 테스트가 빠진 파일을 잡아요.

## 화면 문구

- 사용자에게 보이는 문장은 `~해요` 체로 짧게 쓰고, 다음 행동을 먼저 말해요.
- 라벨은 짧게, 설명은 `app/src/api/tips.ts` 에 모으고 요소에는 `data-tip` 만 붙여요.
- `app/src/api/copy.test.ts` 가 딱딱한 `~습니다` 체를 잡아요.

## 커밋

한 커밋에 한 가지 변경. 제목은 `영역: 무엇을` 형태로 (예: `engine: 자막 단계 추가`, `ui: 업데이트 시트`). 화면이 바뀌면 PR 에 캡처를 붙여 주세요.

## 다른 게임 추가

`games/<게임>.yaml` 에 화면 영역(ROI)과 신호 묶음을 정의하면 돼요. 방법은 [docs/GAME_PROFILE.md](docs/GAME_PROFILE.md) 를 보세요.
