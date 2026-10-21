// 코드 서명 설정: 환경변수만 보고 electron-builder 의 win 설정 조각을 만든다. 인증서·비밀은 저장소에 두지 않는다.
// 어떤 방식이든 설치본 · 앱 실행 파일 · 제거 프로그램이 함께 서명되고, 껍데기 업데이트(electron-updater)는
// publisherName 과 같은 서명이 있는 설치본만 설치한다. 설정 방법은 docs/CODE_SIGNING.md.
//
//   Windows 인증서 저장소   CLIPFORGE_SIGN_SUBJECT="발급 대상 이름" 또는 CLIPFORGE_SIGN_SHA1=<지문>
//                          (클라우드 HSM · USB 토큰 인증서. 예: Certum SimplySign 이 로그인돼 있으면 저장소에 보인다)
//   Azure Artifact Signing CLIPFORGE_AZURE_ENDPOINT · CLIPFORGE_AZURE_ACCOUNT · CLIPFORGE_AZURE_PROFILE
//                          + Microsoft Entra 인증(AZURE_TENANT_ID · AZURE_CLIENT_ID · AZURE_CLIENT_SECRET)
//   외부 명령              CLIPFORGE_SIGN_COMMAND='… "{file}"' — 파일마다 실행 (SignPath · jsign 등)
//   pfx 파일               CSC_LINK · CSC_KEY_PASSWORD (electron-builder 기본 동작)
//   공통                   CLIPFORGE_PUBLISHER = 인증서의 게시자 이름(CN). 업데이트 서명 확인에 쓴다.
//                          게시자를 바꿀 때는 "옛 이름;새 이름" 처럼 ; 로 둘 다 적은 버전을 한 번 낸다 (CN 에 쉼표가 있을 수 있어 ; 로 나눈다)
//                          CLIPFORGE_REQUIRE_SIGNING=1 → 서명 설정이 없으면 빌드를 멈춘다 (릴리스용)
"use strict";
const { execSync } = require("node:child_process");

const TIMESTAMP = "http://timestamp.digicert.com";

/** @param {NodeJS.ProcessEnv} env */
function signingConfig(env = process.env) {
  const names = (env.CLIPFORGE_PUBLISHER || "")
    .split(";")
    .map((s) => s.trim())
    .filter(Boolean);
  const publisher = names.length > 1 ? names : names[0] || null;
  const withPublisher = (win) =>
    publisher ? { ...win, signtoolOptions: { ...win.signtoolOptions, publisherName: publisher } } : win;

  if (env.CLIPFORGE_AZURE_ENDPOINT || env.CLIPFORGE_AZURE_ACCOUNT || env.CLIPFORGE_AZURE_PROFILE) {
    const missing = ["CLIPFORGE_AZURE_ENDPOINT", "CLIPFORGE_AZURE_ACCOUNT", "CLIPFORGE_AZURE_PROFILE"].filter(
      (k) => !env[k],
    );
    if (missing.length) throw new Error(`Azure 서명 설정이 덜 됐어요: ${missing.join(", ")}`);
    return {
      mode: "azure",
      win: withPublisher({
        azureSignOptions: {
          endpoint: env.CLIPFORGE_AZURE_ENDPOINT,
          codeSigningAccountName: env.CLIPFORGE_AZURE_ACCOUNT,
          certificateProfileName: env.CLIPFORGE_AZURE_PROFILE,
        },
      }),
    };
  }
  if (env.CLIPFORGE_SIGN_COMMAND) {
    const template = env.CLIPFORGE_SIGN_COMMAND;
    if (!template.includes("{file}"))
      throw new Error('CLIPFORGE_SIGN_COMMAND 에 서명할 파일 자리 "{file}" 이 있어야 해요');
    return {
      mode: "command",
      win: withPublisher({
        signtoolOptions: {
          sign: (task) => execSync(template.split("{file}").join(task.path), { stdio: "inherit" }),
          signingHashAlgorithms: ["sha256"], // 기본(sha1+sha256)이면 파일마다 명령이 두 번 돈다
        },
      }),
    };
  }
  if (env.CLIPFORGE_SIGN_SUBJECT || env.CLIPFORGE_SIGN_SHA1) {
    return {
      mode: "store",
      win: withPublisher({
        signtoolOptions: {
          ...(env.CLIPFORGE_SIGN_SHA1
            ? { certificateSha1: env.CLIPFORGE_SIGN_SHA1 }
            : { certificateSubjectName: env.CLIPFORGE_SIGN_SUBJECT }),
          signingHashAlgorithms: ["sha256"],
          rfc3161TimeStampServer: env.CLIPFORGE_TIMESTAMP_URL || TIMESTAMP,
        },
      }),
    };
  }
  if (env.CSC_LINK || env.WIN_CSC_LINK) {
    return { mode: "pfx", win: withPublisher({ signtoolOptions: { signingHashAlgorithms: ["sha256"] } }) };
  }
  if (env.CLIPFORGE_REQUIRE_SIGNING === "1") {
    throw new Error("CLIPFORGE_REQUIRE_SIGNING=1 인데 서명 설정이 없어요 — docs/CODE_SIGNING.md 를 보세요");
  }
  return { mode: "none", win: {} };
}

module.exports = { signingConfig };
