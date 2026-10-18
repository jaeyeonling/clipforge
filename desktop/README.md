# clipforge desktop (Electron 껍데기)

```
set PATH=C:\Users\jaeye\tools\node;%PATH%        # 포터블 Node 22
npm install
npm start                                        # 창 + 엔진(저장소 .venv). 8765 에 엔진이 이미 떠 있으면 그것에 붙음
npm run smoke                                    # 자동 점검: 창·엔진 준비 뒤 5초 후 종료 (로그 %APPDATA%\clipforge\shell.log)
set CLIPFORGE_ENGINE_DIST=1 && npm start         # 번들 런타임(../engine-dist)으로 띄우기 (데이터는 저장소)
npm run pack                                     # release/win-unpacked/ (설치본 없이 폴더) → win-unpacked\clipforge.exe --smoke 로 packaged 경로 점검
npm run dist                                     # release/clipforge-Setup-<ver>.exe (NSIS, 사용자 설치, UAC 없음)
set CLIPFORGE_SKIP_ENGINE=1 && npm run pack      # 엔진 없이 빠른 빌드 (툴체인 점검용)
```
설치본 = Electron(~200MB) + `resources/engine/`(= ../engine-dist, `python scripts/build_engine_dist.py --smoke` 로 먼저 구성).
설치본의 데이터 폴더는 `%APPDATA%\clipforge\data` (껍데기가 `CLIPFORGE_DATA` 로 넘김). 제거해도 데이터는 남긴다.

## 파일
- `main.js` 창·트레이·알림·수명, `engine.js` 엔진 사이드카, `preload.js` 렌더러 노출(정보성), `electron-builder.config.js` 패키징, `assets/` 아이콘(임시 마크).

## electron-builder 가 Windows 비관리자에서 멈출 때
`winCodeSign` 7z 안의 macOS 심볼릭 링크 때문에 추출이 실패하고 3번 재시도 뒤 멈춘다 (개발자 모드나 관리자 권한이 없으면 심볼릭 링크를 못 만든다).
한 번만 아래처럼 다운로드 캐시에 직접 풀어 두면 다시는 받지 않는다:
```
set C=%LOCALAPPDATA%\electron-builder\Cache\winCodeSign
node_modules\7zip-bin\win\x64\7za.exe x -y -o%C%\winCodeSign-2.6.0 -xr!darwin %C%\<아무 숫자>.7z
```
(폴더 이름 `winCodeSign-2.6.0` 은 app-builder.exe 가 기대하는 이름. 버전이 바뀌면 `findstr winCodeSign- node_modules\app-builder-bin\win\x64\app-builder.exe` 로 확인.)
코드 서명은 하지 않는다(인증서 없음) — 설치본 첫 실행 때 SmartScreen "추가 정보 → 실행". `CLIPFORGE_NO_RCEDIT=1` 이면 아이콘·버전 정보 삽입도 건너뛴다.
