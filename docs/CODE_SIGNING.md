# 코드 서명

설치본에 서명이 없으면 Windows 가 "Windows의 PC 보호" 창을 띄우고 게시자를 "알 수 없음"으로 보여 줘요.
빌드는 서명할 준비가 돼 있어서, 인증서를 정하고 환경변수만 넣으면 다음 빌드부터 서명돼요.

## 서명되는 것

- 설치본(`clipforge-Setup-x.y.z.exe`), 앱 실행 파일(`clipforge.exe`), 제거 프로그램. 타임스탬프를 함께 찍어서 인증서가 만료된 뒤에도 서명은 유효해요.
- 껍데기 업데이트(층 C)는 앱에 적힌 게시자 이름과 **같은 서명**이 있는 설치본만 설치해요. 서명 없이 나간 버전은 게시자 이름이 비어 있어서, 서명된 다음 버전으로 그대로 업데이트돼요.
- 처음 실행 때 받는 구성요소(파이썬 · FFmpeg · 모델)와 앱 코드 업데이트(층 A · B)는 서명 대신 릴리스 매니페스트의 SHA-256 으로 확인해요.

서명은 신뢰를 쌓는 출발점이에요. 새 인증서는 SmartScreen 평판이 쌓이기 전까지 경고가 남을 수 있어요.

## 인증서 고르기

2023년부터 코드 서명 인증서의 개인 키는 하드웨어(HSM · 보안 토큰)에만 둘 수 있어서, 대부분 클라우드 서명이나 토큰으로 받아요.

| 방법 | 누가 | 비용 | 이 저장소에서 쓰는 방식 |
|---|---|---|---|
| [SignPath Foundation](https://signpath.org/) | OSI 라이선스 오픈소스 (공개 저장소, CI 자동 빌드) | 무료 | 외부 명령 (`CLIPFORGE_SIGN_COMMAND`). 게시자는 SignPath Foundation 으로 표시돼요 |
| [Certum](https://shop.certum.eu/code-signing.html) 클라우드 인증서 (SimplySign) | 개인 · 사업자 | 연 단위 유료 | Windows 인증서 저장소 (`CLIPFORGE_SIGN_SUBJECT`) |
| [Azure Artifact Signing](https://learn.microsoft.com/azure/artifact-signing/quickstart) | 조직(한국 포함). 개인은 미국 · 캐나다만 | 월 구독 | Azure (`CLIPFORGE_AZURE_*`) |
| pfx 파일 | 이미 가진 인증서 | — | `CSC_LINK` · `CSC_KEY_PASSWORD` |

정해야 하는 건 저장소 주인이에요(본인 확인 · 결제). 조건과 가격은 바뀌므로 신청 전에 각 페이지에서 확인하세요.

## 설정

비밀 값은 저장소나 채팅에 두지 말고, 빌드하는 터미널의 환경변수나 CI 비밀 값으로만 넣어요.

```powershell
# 공통: 인증서의 게시자 이름(CN). 업데이트 서명 확인에 쓰여요
$env:CLIPFORGE_PUBLISHER = "인증서 CN"

# Windows 인증서 저장소 (Certum SimplySign 에 로그인하면 저장소에 인증서가 보여요)
$env:CLIPFORGE_SIGN_SUBJECT = "인증서 CN"          # 같은 이름이 여럿이면 대신 CLIPFORGE_SIGN_SHA1 = 지문

# Azure Artifact Signing
$env:CLIPFORGE_AZURE_ENDPOINT = "https://<지역>.codesigning.azure.net"
$env:CLIPFORGE_AZURE_ACCOUNT  = "<서명 계정 이름>"
$env:CLIPFORGE_AZURE_PROFILE  = "<인증서 프로필 이름>"
# + AZURE_TENANT_ID · AZURE_CLIENT_ID · AZURE_CLIENT_SECRET (Microsoft Entra 앱 등록)

# 외부 명령: 파일마다 한 번 실행돼요. {file} 자리에 서명할 파일 경로가 들어가요
$env:CLIPFORGE_SIGN_COMMAND = 'my-sign.cmd "{file}"'
```

빌드 로그 첫 줄에 `[sign] 서명 방식: …` 이 나오면 설정이 잡힌 거예요. 어떤 방식을 고르는지는 [`desktop/signing.js`](../desktop/signing.js) 에 있어요.

## 릴리스

```powershell
$env:CLIPFORGE_REQUIRE_SIGNING = "1"                  # 서명 설정이 없으면 빌드가 멈춰요
python scripts\publish_github.py app --require-signed # 설치본 서명이 Valid 가 아니면 올리지 않아요
```

올리기 전에 `Get-AuthenticodeSignature .\desktop\release\clipforge-Setup-*.exe` 로 상태가 `Valid` 인지, 서명자가 맞는지 확인할 수 있어요.

## 게시자를 바꿀 때

설치된 앱은 자기에게 적힌 게시자 이름과 같은 서명만 업데이트로 받아요. 인증서를 바꾸면(예: SignPath Foundation → 본인 인증서) 이름이 달라지므로 두 번에 나눠 내요.

1. **옛 인증서로 서명**하면서 두 이름을 모두 믿는 버전. 지금 설치된 앱이 옛 서명을 확인하고 받아요.
   ```powershell
   $env:CLIPFORGE_PUBLISHER = "옛 게시자 CN; 새 게시자 CN"   # CN 에 쉼표가 있을 수 있어 ; 로 나눠요
   ```
2. 그 버전이 퍼진 뒤 **새 인증서로 서명**하고 새 이름만 둔 버전. 1번이 깔린 앱은 새 이름도 믿으므로 받아요.
