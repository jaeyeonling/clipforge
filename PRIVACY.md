# 개인정보

clipforge 는 모든 분석을 이 PC 에서 해요. 계정 · 원격 분석(telemetry) · 오류 보고 전송이 없어요.

## 이 PC 밖으로 나가지 않는 것

영상, 전사 · 자막, 쇼츠 초안, 판정(쓸 만함 / 안 씀), 화면 영역 설정, 로그. 전부 `%LOCALAPPDATA%\clipforge` 와 고른 영상 폴더에만 있어요.
분석 엔진은 `127.0.0.1` 에서만 열리고, 브라우저로 연 다른 사이트의 요청은 거절해요.

## 앱이 접속하는 곳

| 어디 | 언제 | 무엇을 |
|---|---|---|
| GitHub (`github.com`, `api.github.com`, 릴리스 파일 서버) | 켤 때와 몇 시간마다 업데이트 확인, 처음 실행 · 업데이트 때 내려받기 | 새 버전 목록(`latest.json`)과 설치본 · 엔진 구성요소 파일을 받아요 |
| PyPI (`files.pythonhosted.org`) | 처음 실행 때, GPU 가속을 고른 경우에만 | NVIDIA 가 올린 GPU 가속 라이브러리를 받아요 |
| OBS WebSocket | 라이브 탭에서 연결할 때만 | 직접 적은 주소(기본은 이 PC)의 OBS 와 텍스트 소스를 주고받아요 |

이 요청들은 파일을 받기만 해요. 보내는 것은 일반적인 HTTP 요청 정보(IP 주소, `clipforge` 라는 user-agent)뿐이고, 그 처리는 각 서비스의 정책을 따라요:
[GitHub](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement) ·
[PyPI](https://policies.python.org/pypi.org/Privacy-Notice/).

비공개 저장소용 GitHub 토큰을 넣었다면(`%LOCALAPPDATA%\clipforge\github-token.txt`), 그 토큰은 GitHub 요청에만 쓰여요.

---

**English summary.** clipforge processes everything on your PC and has no accounts, telemetry or crash reporting. Videos, transcripts, drafts and judgments never leave the machine; the engine listens on 127.0.0.1 only. The app connects to GitHub to check for and download updates and engine components, to PyPI (files.pythonhosted.org) to download NVIDIA GPU libraries on first run if GPU acceleration is selected, and to OBS only at the address you enter. These requests only download files; the services see ordinary HTTP request data (IP address, user agent).
