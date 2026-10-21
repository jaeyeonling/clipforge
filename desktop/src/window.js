// 창 · 앱 화면(부팅 · 설치) · 알림 · 보안 기본값.
//   부팅 · 설치 화면은 file:// 대신 clipforge://app/ 으로 연다: 표준 · 보안 스킴이라 CSP 'self' 가 그대로 통한다.
//   창이 갈 수 있는 곳은 엔진 화면(127.0.0.1:<포트>)과 앱 화면뿐. 권한 요청은 클립보드 쓰기만 허용한다.
"use strict";
const { app, BrowserWindow, Menu, Notification, net, protocol, session, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const state = require("./state");
const { log } = require("./log");

const ASSETS = path.join(__dirname, "..", "assets");
const PAGES = path.join(__dirname, "pages");
const SCHEME = "clipforge";
const PAGE_ORIGIN = `${SCHEME}://app`;
const ALLOWED_PERMISSIONS = new Set(["clipboard-sanitized-write"]); // 화면의 "경로 복사"

/** app ready 전에 불러야 한다. */
function registerPageScheme() {
  protocol.registerSchemesAsPrivileged([{ scheme: SCHEME, privileges: { standard: true, secure: true } }]);
}

/** pages/ 아래에 있는 파일만 내준다. 인코딩된 역슬래시(..%5C) 같은 우회도 폴더 밖이면 null → 404. */
function pageFile(url) {
  const u = new URL(url);
  if (u.host !== "app") return null;
  let rel;
  try {
    rel = decodeURIComponent(u.pathname);
  } catch {
    return null;
  }
  const file = path.normalize(path.join(PAGES, rel));
  return file.startsWith(PAGES + path.sep) && fs.existsSync(file) ? file : null;
}

/** 창이 갈 수 있는 곳: 앱 화면과, 떠 있는 엔진의 화면. */
function isAppUrl(url) {
  if (url.startsWith(PAGE_ORIGIN + "/")) return true;
  const engineUrl = state.engine?.url;
  if (!engineUrl) return false;
  try {
    return new URL(url).origin === new URL(engineUrl).origin;
  } catch {
    return false;
  }
}

/** app ready 뒤: 앱 화면 스킴 처리 + 세션 · 웹 콘텐츠 보안 기본값. */
function installSecurity() {
  protocol.handle(SCHEME, (req) => {
    const file = pageFile(req.url);
    return file ? net.fetch(pathToFileURL(file).toString()) : new Response("not found", { status: 404 });
  });
  const ses = session.defaultSession;
  ses.setPermissionRequestHandler((_wc, permission, cb) => cb(ALLOWED_PERMISSIONS.has(permission)));
  ses.setPermissionCheckHandler((_wc, permission) => ALLOWED_PERMISSIONS.has(permission));
  app.on("web-contents-created", (_e, contents) => {
    contents.on("will-attach-webview", (e) => e.preventDefault());
    contents.on("will-navigate", (e, url) => {
      if (isAppUrl(url)) return;
      e.preventDefault();
      log(`shell: 앱 밖으로 이동 막음 ${url}`);
    });
    // 새 창은 열지 않는다. 바깥 링크(https)는 기본 브라우저로.
    contents.setWindowOpenHandler(({ url }) => {
      if (/^https?:\/\//.test(url) && !isAppUrl(url)) shell.openExternal(url);
      return { action: "deny" };
    });
  });
}

/** 메뉴는 숨기지만(autoHideMenuBar) 편집·보기 단축키는 살린다: Ctrl+C/V/X/A/Z, Ctrl+R, F12. */
function installMenu() {
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      {
        label: "편집",
        submenu: [
          { role: "undo", label: "실행 취소" },
          { role: "redo", label: "다시 실행" },
          { type: "separator" },
          { role: "cut", label: "잘라내기" },
          { role: "copy", label: "복사" },
          { role: "paste", label: "붙여넣기" },
          { role: "selectAll", label: "전체 선택" },
        ],
      },
      {
        label: "보기",
        submenu: [
          { role: "reload", label: "새로고침" },
          { role: "toggleDevTools", label: "개발자 도구" },
          { type: "separator" },
          { role: "resetZoom", label: "원래 크기" },
          { role: "zoomIn", label: "확대" },
          { role: "zoomOut", label: "축소" },
          { type: "separator" },
          { role: "togglefullscreen", label: "전체 화면" },
        ],
      },
    ]),
  );
}

/** 오른쪽 클릭 메뉴: 복사·붙여넣기·전체 선택. Electron 은 기본 컨텍스트 메뉴가 없어서 직접 단다. */
function contextMenu(win, params) {
  const ef = params.editFlags || {};
  const items = [];
  if (params.isEditable) {
    items.push(
      { role: "undo", label: "실행 취소", enabled: ef.canUndo },
      { role: "redo", label: "다시 실행", enabled: ef.canRedo },
      { type: "separator" },
      { role: "cut", label: "잘라내기", enabled: ef.canCut },
      { role: "copy", label: "복사", enabled: ef.canCopy },
      { role: "paste", label: "붙여넣기", enabled: ef.canPaste },
      { type: "separator" },
      { role: "selectAll", label: "전체 선택" },
    );
  } else if (params.selectionText && params.selectionText.trim()) {
    items.push({ role: "copy", label: "복사" });
  }
  if (params.linkURL)
    items.push({ label: "링크 복사", click: () => require("electron").clipboard.writeText(params.linkURL) });
  if (params.mediaType === "image" && params.srcURL)
    items.push({ label: "이미지 복사", click: () => win.webContents.copyImageAt(params.x, params.y) });
  if (!items.length) items.push({ role: "selectAll", label: "전체 선택" });
  Menu.buildFromTemplate(items).popup({ window: win });
}

function createWindow() {
  installMenu();
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 980,
    minHeight: 640,
    backgroundColor: "#17171c",
    title: "clipforge",
    show: false,
    icon: path.join(ASSETS, "icon.png"),
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  state.win = win;
  win.once("ready-to-show", () => win.show());
  win.webContents.on("context-menu", (_e, params) => contextMenu(win, params));
  showBoot("엔진을 준비하는 중…", "", true);
  win.on("close", (e) => {
    if (state.quitting) return;
    e.preventDefault();
    win.hide();
    if (!app._hintShown) {
      app._hintShown = true;
      notify("트레이에서 계속 실행 중", "작업과 다운로드는 계속돼요. 트레이 아이콘에서 다시 열거나 종료하세요.");
    }
  });
  win.on("closed", () => (state.win = null));
  return win;
}

function showWindow() {
  if (!state.win) createWindow();
  const win = state.win;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

/** 부팅 · 업데이트 · 오류 화면. 문구는 쿼리로 넘기고 화면이 textContent 로만 넣는다. */
function showBoot(title, detail = "", spinning = false) {
  const q = new URLSearchParams({ title, detail, spin: spinning ? "1" : "" });
  return state.win?.loadURL(`${PAGE_ORIGIN}/boot.html?${q}`);
}

function showSetupPage() {
  return state.win?.loadURL(`${PAGE_ORIGIN}/setup.html`);
}

/** OS 알림. onClick 이 있으면 알림을 눌렀을 때 부른다. */
function notify(title, body, onClick) {
  if (!Notification.isSupported()) return;
  try {
    const n = new Notification({ title, body, icon: path.join(ASSETS, "icon.png") });
    if (onClick) n.on("click", onClick);
    n.show();
  } catch (e) {
    log(`notify 실패 ${e.message}`);
  }
}

module.exports = {
  ASSETS,
  PAGE_ORIGIN,
  registerPageScheme,
  installSecurity,
  isAppUrl,
  pageFile,
  createWindow,
  showWindow,
  showBoot,
  showSetupPage,
  notify,
};
