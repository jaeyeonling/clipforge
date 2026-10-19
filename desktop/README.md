# clipforge desktop (Electron 껍데기)

```
set PATH=C:\Users\jaeye\tools\node;%PATH%        # 포터블 Node 22
npm install
npm start                                        # 창 + 엔진(저장소 .venv). 8765 에 엔진이 이미 떠 있으면 그것에 붙음
npm run smoke                                    # 자동 점검: 창·엔진 준비 뒤 5초 후 종료 (로그 %APPDATA%\clipforge\shell.log)
npx electron . --smoke-setup                     # (런타임 모드) 첫 실행 설치 화면만 캡처 (%APPDATA%\clipforge\smoke-setup.png)
npx electron . --smoke --smoke-tab=pipeline --fake-update   # 가짜 업데이트 상태로 '새 버전이 준비됐어요' 시트·배너 캡처 (%APPDATA%\clipforge\smoke.png)
set CLIPFORGE_ENGINE_DIST=1 && npm start         # 번들 런타임(../engine-dist)으로 띄우기 (데이터는 저장소)
npm run pack                                     # release/win-unpacked/ (설치본 없이 폴더) → win-unpacked\clipforge.exe --smoke 로 packaged 경로 점검
npm run dist                                     # release/clipforge-Setup-<ver>.exe (NSIS, 사용자 설치, UAC 없음)
set CLIPFORGE_SKIP_ENGINE=1 && npm run pack      # 엔진 없이 빠른 빌드 (툴체인 점검용)
```
설치본 = Electron + 엔진 코드(resources/engine: ../engine-dist 의 clipforge/ games/ data/ assets/ app/dist 만) + 7za.exe ≈ 100MB.
대용량 구성요소(파이썬 런타임·CUDA·ffmpeg·Whisper)는 첫 실행 때 `latest.json` 을 보고 받아 `%LOCALAPPDATA%\clipforge\runtime\` 에 둔다.
데이터는 `%LOCALAPPDATA%\clipforge\data`. 제거해도 런타임·데이터는 남긴다.
구성요소는 **3개씩 동시에** 받고(`components.apply` concurrency), 받아진 것부터 순서대로 푼다(python-base → cuda 순서 보장). 설치 화면은 기다리는 동안 서비스 소개 슬라이드 5장을 돌린다.

## 릴리스 아티팩트 · 첫 실행 흐름 점검
```
python scripts/build_engine_dist.py --release release-test --release-components --base-url file:///C:/Users/jaeye/source/clipforge/release-test
set CLIPFORGE_RUNTIME_DIR=%TEMP%\cf-runtime-test
set CLIPFORGE_UPDATE_URL=file:///C:/Users/jaeye/source/clipforge/release-test
npm start                                        # 첫 실행 설치 화면 → 구성요소 선택 → 설치 → 엔진 시작
npx electron . --auto-setup --smoke              # 같은 흐름을 클릭 없이 끝까지 (자동 점검)
```
업데이트 주소 우선순위: `CLIPFORGE_UPDATE_URL` → `%LOCALAPPDATA%\clipforge\update-url.txt` → `release.config.js`(GitHub Releases `jaeyeonling/clipforge`, 최신 릴리스).

## GitHub Releases 배포 (private 저장소)
```
set PATH=C:\Users\jaeye\tools\gh\bin;%PATH%
gh auth login                                    # 한 번 (브라우저)
python scripts\publish_github.py runtime         # 런타임 릴리스 runtime-YYYY.MM (구성요소 zip 4개, 처음 한 번)
python scripts\publish_github.py app             # 앱 릴리스 v<ver>: 화면 빌드 → 엔진 코드 zip·latest.json → NSIS → 업로드
python scripts\publish_github.py app --dry-run   # 올리지 않고 만들 것만 확인
```
private 저장소라 **사용자 PC 에 읽기 전용 토큰**이 필요하다: GitHub → Settings → Developer settings → Fine-grained tokens → Repository access: clipforge, Permissions: Contents Read-only →
토큰을 `%LOCALAPPDATA%\clipforge\github-token.txt` 에 저장(한 줄). 없으면 첫 실행 화면이 안내한다. 저장소를 public 으로 바꾸면 토큰이 필요 없다.

## 파일
- `main.js` 창·트레이·알림·첫 실행 설치·업데이트 적용·오른쪽 클릭 복사/붙여넣기 메뉴·편집/보기 메뉴(숨김, 단축키만), `engine.js` 엔진 사이드카(모드: runtime/dist/venv), `components.js` 구성요소 다운로드·설치·롤백, `preload.js` IPC 브리지, `electron-builder.config.js` 패키징, `assets/` 아이콘(임시 마크).

## electron-builder 가 Windows 비관리자에서 멈출 때
`winCodeSign` 7z 안의 macOS 심볼릭 링크 때문에 추출이 실패하고 3번 재시도 뒤 멈춘다 (개발자 모드나 관리자 권한이 없으면 심볼릭 링크를 못 만든다).
한 번만 아래처럼 다운로드 캐시에 직접 풀어 두면 다시는 받지 않는다:
```
set C=%LOCALAPPDATA%\electron-builder\Cache\winCodeSign
node_modules\7zip-bin\win\x64\7za.exe x -y -o%C%\winCodeSign-2.6.0 -xr!darwin %C%\<아무 숫자>.7z
```
(폴더 이름 `winCodeSign-2.6.0` 은 app-builder.exe 가 기대하는 이름. 버전이 바뀌면 `findstr winCodeSign- node_modules\app-builder-bin\win\x64\app-builder.exe` 로 확인.)
코드 서명은 하지 않는다(인증서 없음) — 설치본 첫 실행 때 SmartScreen "추가 정보 → 실행". `CLIPFORGE_NO_RCEDIT=1` 이면 아이콘·버전 정보 삽입도 건너뛴다.
