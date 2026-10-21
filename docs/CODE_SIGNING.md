# 코드 서명

설치본에 서명이 없으면 Windows 가 "Windows의 PC 보호" 창을 띄우고 게시자를 "알 수 없음"으로 보여 줘요.
clipforge 는 오픈소스 프로젝트에 무료로 인증서를 주는 [SignPath Foundation](https://signpath.org) 으로 서명해요.
서명하는 쪽은 [SignPath.io](https://about.signpath.io) 이고, 인증서의 게시자는 "SignPath Foundation" 으로 보여요.

## 무엇이 어떻게 서명되나요

v* 태그를 올리면 [`.github/workflows/release.yml`](../.github/workflows/release.yml) 이 GitHub 가 호스팅하는 Windows 러너에서 이렇게 해요.

1. 화면을 빌드하고 엔진 코드 번들과 앱 내 업데이트 매니페스트(`latest.json`)를 만들어요.
2. 앱 폴더를 만들고 `clipforge.exe` 를 GitHub 아티팩트로 올려 SignPath 에 서명을 요청해요. ([artifact configuration `app-exe`](../.signpath/artifact-configurations/app-exe.xml))
3. 서명된 앱 폴더로 NSIS 설치본을 만들어 다시 서명을 요청해요. ([`installer`](../.signpath/artifact-configurations/installer.xml))
4. 서명으로 바뀐 설치본 기준으로 `latest.yml` 의 해시와 차등 업데이트용 blockmap 을 다시 계산하고, 두 파일의 서명이 유효한지 확인해요.
5. 릴리스 초안을 만들어요. 확인한 뒤 공개해요.

- SignPath 는 서명할 파일이 **이 실행이 이 저장소의 소스로 만든 GitHub 아티팩트인지** 확인해요. 로컬에서 만든 파일은 서명받을 수 없어요.
- 서명 요청마다 승인자가 SignPath 에서 직접 승인해요. 워크플로는 승인을 기다려요(최대 1시간).
- 제품 이름(`clipforge`)과 버전이 artifact configuration 과 맞아야 서명돼요.
- 제거 프로그램은 설치본 안에서 만들어져 설치본의 서명이 감싸요. 설치된 폴더에서만 실행돼 SmartScreen 검사 대상이 아니에요.
- 처음 실행 때 받는 구성요소(파이썬 · FFmpeg · 모델)와 앱 코드 업데이트는 서명 대신 매니페스트의 SHA-256 으로 확인해요. GPU 가속 라이브러리는 NVIDIA 가 PyPI 에 올린 휠을 그대로 받아요 — 이 저장소의 릴리스에 독점 바이너리를 다시 올리지 않아요.
- 껍데기 업데이트는 앱에 적힌 게시자(SignPath Foundation)와 **같은 서명**이 있는 설치본만 설치해요. 서명 없이 나간 버전은 게시자 이름이 비어 있어서 서명된 다음 버전으로 그대로 업데이트돼요.

서명은 신뢰를 쌓는 출발점이에요. 새 인증서는 SmartScreen 평판이 쌓이기 전까지 경고가 남을 수 있어요.

## 처음 한 번 (저장소 주인)

SignPath Foundation 의 [조건](https://signpath.org/terms): OSI 라이선스(MIT) · 독점 구성요소 없음 · 서명할 형태로 이미 릴리스됨 · README 의 코드 서명 정책 · 팀원 다중 인증.

1. 저장소를 공개하고, 서명 없는 첫 릴리스(v0.3.0)를 이 워크플로로 낸다.
2. GitHub 계정에 2단계 인증을 켠다.
3. [signpath.org](https://signpath.org) 에서 신청한다. 저장소 주소, 다운로드 페이지(GitHub Releases), 코드 서명 정책([README 의 절](../README.md#코드-서명-정책-code-signing-policy)), 빌드 방식(GitHub Actions)을 적는다.
4. 승인되면 SignPath 에서:
   - 조직에 **GitHub.com trusted build system** 을 추가하고 프로젝트에 연결한다.
   - 프로젝트 slug `clipforge`, 서명 정책 slug `release-signing` (승인자: 저장소 주인).
   - artifact configuration 두 개를 `.signpath/artifact-configurations/` 의 XML 그대로 만든다: `app-exe`, `installer`.
   - 서명 요청을 올릴 CI 사용자를 만들고 API 토큰을 발급한다 (submitter 권한).
   - SignPath 계정에도 다중 인증을 켠다.
5. GitHub 저장소 → Settings → Secrets and variables → Actions:

   | 종류 | 이름 | 값 |
   |---|---|---|
   | Secret | `SIGNPATH_API_TOKEN` | 4번의 API 토큰 |
   | Variable | `SIGNPATH_ORGANIZATION_ID` | SignPath 조직 ID |
   | Variable (선택) | `SIGNPATH_PROJECT_SLUG` · `SIGNPATH_SIGNING_POLICY_SLUG` | 기본값과 다를 때 |
   | Variable (선택) | `SIGNPATH_PUBLISHER` | 인증서 게시자 이름이 `SignPath Foundation` 이 아닐 때 |

토큰 같은 비밀 값은 저장소 파일이나 채팅에 두지 말고 GitHub 비밀 값으로만 넣어요.
설정이 없으면 워크플로는 같은 과정을 서명 없이 거치고 경고를 남겨요.

## 릴리스

1. `clipforge/__init__.py` · `desktop/package.json` 의 버전과 `CHANGELOG.md` 를 올린다.
2. `git tag v0.3.0 && git push origin v0.3.0`
3. SignPath 에서 서명 요청 두 개(앱 실행 파일 → 설치본)를 승인한다.
4. 초안 릴리스에서 설치본을 받아 파일 속성 → 디지털 서명이 "SignPath Foundation" 인지 확인하고 공개한다.

런타임 구성요소 릴리스(`runtime-YYYY.MM`)는 서명 대상이 아니라 로컬에서 `python scripts\publish_github.py runtime` 으로 올려요.

## 다른 인증서로 로컬에서 서명하기

SignPath 없이 로컬에서 만든 설치본은 환경변수로 서명 방식을 고를 수 있어요. 고르는 규칙은 [`desktop/signing.js`](../desktop/signing.js) 에 있어요.

```powershell
$env:CLIPFORGE_PUBLISHER = "인증서 CN"                # 업데이트 서명 확인에 쓰여요
$env:CLIPFORGE_SIGN_SUBJECT = "인증서 CN"             # Windows 인증서 저장소 (클라우드 HSM · 토큰). 지문이면 CLIPFORGE_SIGN_SHA1
$env:CLIPFORGE_AZURE_ENDPOINT = "https://<지역>.codesigning.azure.net"   # Azure Artifact Signing
$env:CLIPFORGE_AZURE_ACCOUNT  = "<서명 계정>"; $env:CLIPFORGE_AZURE_PROFILE = "<인증서 프로필>"
$env:CLIPFORGE_SIGN_COMMAND = 'my-sign.cmd "{file}"'  # 외부 명령, 파일마다 한 번
# pfx 파일: CSC_LINK · CSC_KEY_PASSWORD
$env:CLIPFORGE_REQUIRE_SIGNING = "1"                  # 서명 설정이 없으면 빌드를 멈춰요
python scripts\publish_github.py app --require-signed # 설치본 서명이 Valid 가 아니면 올리지 않아요
```

| 다른 선택지 | 누가 |
|---|---|
| [Certum](https://shop.certum.eu/code-signing.html) 클라우드 인증서 (SimplySign) | 개인 · 사업자, 연 단위 유료. 로그인하면 Windows 인증서 저장소에 보여요 |
| [Azure Artifact Signing](https://learn.microsoft.com/azure/artifact-signing/quickstart) | 조직(한국 포함). 개인은 미국 · 캐나다만 |

## 게시자를 바꿀 때

설치된 앱은 자기에게 적힌 게시자 이름과 같은 서명만 업데이트로 받아요. 인증서를 바꾸면(예: SignPath Foundation → 본인 인증서) 이름이 달라지므로 두 번에 나눠 내요.

1. **옛 인증서로 서명**하면서 두 이름을 모두 믿는 버전. 지금 설치된 앱이 옛 서명을 확인하고 받아요.
   GitHub 변수 `SIGNPATH_PUBLISHER` (로컬이면 `CLIPFORGE_PUBLISHER`) 를 `옛 게시자 CN; 새 게시자 CN` 으로 둬요 (CN 에 쉼표가 있을 수 있어 ; 로 나눠요).
2. 그 버전이 퍼진 뒤 **새 인증서로 서명**하고 새 이름만 둔 버전. 1번이 깔린 앱은 새 이름도 믿으므로 받아요.
