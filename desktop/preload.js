// 렌더러에 노출하는 최소 API (contextIsolation + sandbox).
//   - React 화면은 HTTP/WS 로 엔진과 직접 대화한다. 껍데기에만 있는 정보/동작(버전·업데이트·폴더 열기)만 여기로.
//   - 첫 실행 설치 화면(main.js 의 data: URL)도 같은 preload 를 쓴다 (setup.*).
//   - 브라우저로 열면 window.clipforgeShell 이 없다 → 화면은 그 부분을 숨긴다.
const { contextBridge, ipcRenderer, webUtils } = require("electron");

const on = (channel) => (cb) => {
  const h = (_e, v) => cb(v);
  ipcRenderer.on(channel, h);
  return () => ipcRenderer.removeListener(channel, h);
};

contextBridge.exposeInMainWorld("clipforgeShell", {
  platform: process.platform,
  versions: { electron: process.versions.electron, node: process.versions.node, chrome: process.versions.chrome },
  setup: {
    onEvent: on("setup:event"),
    ready: () => ipcRenderer.invoke("setup:ready"),
    start: (opts) => ipcRenderer.invoke("setup:start", opts || {}),
    cancel: () => ipcRenderer.invoke("setup:cancel"),
    openLogs: () => ipcRenderer.invoke("shell:openLogs"),
  },
  update: {
    state: () => ipcRenderer.invoke("update:state"), // {checking, pending:[{name,version,size,reason}], shell:{version}|null, applying, lastCheck, error}
    onState: on("update:state"),
    check: () => ipcRenderer.invoke("update:check"),
    apply: () => ipcRenderer.invoke("update:apply"), // 층 A·B (엔진 재시작)
    applyShell: () => ipcRenderer.invoke("update:applyShell"), // 층 C (앱 재시작)
  },
  shell: {
    pickVideos: () => ipcRenderer.invoke("shell:pickVideos"), // 파일 선택 대화상자 → 경로 배열
    pathForFile: (file) => webUtils.getPathForFile(file), // 드래그 앤 드롭된 File → 실제 경로
    info: () => ipcRenderer.invoke("shell:info"), // {mode, runtimeDir, dataRoot, logDir, updateUrl, isPrivate, hasToken, versions:{engine, components}, shellVersion}
    openLogs: () => ipcRenderer.invoke("shell:openLogs"),
    openPath: (p) => ipcRenderer.invoke("shell:openPath", p),
  },
});
