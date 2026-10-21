# 보안 정책

## 이 앱이 하는 것과 하지 않는 것

- 분석 엔진은 **127.0.0.1 에만** 열려요. 같은 PC 밖에서는 접속할 수 없어요.
- 같은 PC 의 브라우저에 열린 다른 웹사이트도 엔진을 쓸 수 없어요. 요청의 Host 가 로컬 이름이 아니거나(DNS 리바인딩) Origin 이 다른 사이트이거나 `null`(샌드박스 iframe 등)이면 HTTP 는 403, WebSocket 은 연결을 닫아요 (`clipforge/api/server.py` `LocalOnlyMiddleware`, 테스트 `test_engine_refuses_other_sites_and_rebinding`).
- 영상과 분석 결과는 사용자 PC 의 데이터 폴더(`%LOCALAPPDATA%\clipforge\data`)에만 있어요. 외부로 보내는 일은 없어요.
- 네트워크를 쓰는 곳은 두 군데예요. 첫 실행·업데이트 때 GitHub Releases 에서 구성요소를 받는 것과, 라이브 탭에서 사용자가 직접 입력한 OBS WebSocket 주소(기본은 같은 PC)예요.
- 받은 구성요소는 매니페스트의 SHA-256 으로 검사하고, 틀리면 설치하지 않아요. 설치 중 실패하면 이전 버전으로 되돌려요.
- "피드백 zip" 에는 판정·작업 기록·로그만 들어가고 영상과 캐시는 들어가지 않아요.
- 서명된 릴리스가 나오기 전 설치본은 서명이 없어요. Releases 의 파일만 받아 주세요. 서명된 뒤에는 파일 속성의 "디지털 서명" 탭에서 게시자가 SignPath Foundation 인지 확인할 수 있어요 ([CODE_SIGNING.md](docs/CODE_SIGNING.md)).

## 취약점 알리기

공개 이슈 대신 GitHub 의 **Security → Report a vulnerability** (비공개 보고)로 알려 주세요. 확인하면 답을 드리고, 고친 뒤 변경 내역에 적을게요.

지원 버전은 최신 릴리스 하나예요.
