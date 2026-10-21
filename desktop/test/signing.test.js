// 코드 서명 설정: 환경변수 조합마다 electron-builder 에 넘어가는 win 설정이 맞는지.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { signingConfig } = require("../signing");

test("서명 설정이 없으면 서명 없이 빌드하고, 업데이트 게시자 확인도 켜지 않는다", () => {
  const s = signingConfig({});
  assert.equal(s.mode, "none");
  assert.deepEqual(s.win, {});
});

test("릴리스에서 서명을 요구하면 설정이 없을 때 빌드를 멈춘다", () => {
  assert.throws(() => signingConfig({ CLIPFORGE_REQUIRE_SIGNING: "1" }), /서명 설정이 없어요/);
});

test("인증서 저장소: 발급 대상 이름으로 sha256 서명 + 타임스탬프, 게시자 이름은 업데이트 확인용으로", () => {
  const s = signingConfig({ CLIPFORGE_SIGN_SUBJECT: "Open Source Developer, Jaeyeon", CLIPFORGE_PUBLISHER: "Jaeyeon" });
  assert.equal(s.mode, "store");
  assert.equal(s.win.signtoolOptions.certificateSubjectName, "Open Source Developer, Jaeyeon");
  assert.deepEqual(s.win.signtoolOptions.signingHashAlgorithms, ["sha256"]);
  assert.match(s.win.signtoolOptions.rfc3161TimeStampServer, /^http/);
  assert.equal(s.win.signtoolOptions.publisherName, "Jaeyeon");
});

test("인증서 저장소: 지문이 있으면 지문으로 고른다", () => {
  const s = signingConfig({ CLIPFORGE_SIGN_SUBJECT: "x", CLIPFORGE_SIGN_SHA1: "ABCD" });
  assert.equal(s.win.signtoolOptions.certificateSha1, "ABCD");
  assert.equal(s.win.signtoolOptions.certificateSubjectName, undefined);
});

test("Azure: 세 값이 다 있어야 하고, 하나라도 빠지면 무엇이 빠졌는지 알려 준다", () => {
  const ok = signingConfig({
    CLIPFORGE_AZURE_ENDPOINT: "https://krc.codesigning.azure.net",
    CLIPFORGE_AZURE_ACCOUNT: "acct",
    CLIPFORGE_AZURE_PROFILE: "prof",
  });
  assert.equal(ok.mode, "azure");
  assert.deepEqual(ok.win.azureSignOptions, {
    endpoint: "https://krc.codesigning.azure.net",
    codeSigningAccountName: "acct",
    certificateProfileName: "prof",
  });
  assert.throws(
    () => signingConfig({ CLIPFORGE_AZURE_ENDPOINT: "e" }),
    /CLIPFORGE_AZURE_ACCOUNT, CLIPFORGE_AZURE_PROFILE/,
  );
});

test("외부 명령: 파일 자리가 없으면 거절, 있으면 파일마다 한 번(sha256) 실행", () => {
  assert.throws(() => signingConfig({ CLIPFORGE_SIGN_COMMAND: "sign.cmd" }), /\{file\}/);
  const s = signingConfig({ CLIPFORGE_SIGN_COMMAND: 'sign.cmd "{file}"' });
  assert.equal(s.mode, "command");
  assert.equal(typeof s.win.signtoolOptions.sign, "function");
  assert.deepEqual(s.win.signtoolOptions.signingHashAlgorithms, ["sha256"]);
});

test("pfx: electron-builder 기본(CSC_LINK)에 맡기되 sha256 만", () => {
  const s = signingConfig({ CSC_LINK: "C:/cert.pfx" });
  assert.equal(s.mode, "pfx");
  assert.deepEqual(s.win.signtoolOptions.signingHashAlgorithms, ["sha256"]);
});

test("게시자를 바꿀 때: ; 로 옛 이름과 새 이름을 함께 믿게 한다 (CN 안의 쉼표는 그대로)", () => {
  const s = signingConfig({
    CLIPFORGE_SIGN_SUBJECT: "x",
    CLIPFORGE_PUBLISHER: "SignPath Foundation; Open Source Developer, Jaeyeon",
  });
  assert.deepEqual(s.win.signtoolOptions.publisherName, ["SignPath Foundation", "Open Source Developer, Jaeyeon"]);
});
