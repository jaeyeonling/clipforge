// 렌더러에 노출하는 최소 API.
//   - React 화면은 HTTP/WS 로 엔진과 직접 대화하므로 정보성 값만.
//   - 첫 실행 설치 화면(setup page, main.js 가 만드는 data: URL)은 IPC 로 진행 상황을 받고 시작/취소를 보낸다.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("clipforgeShell", {
  platform: process.platform,
  versions: { electron: process.versions.electron, node: process.versions.node, chrome: process.versions.chrome },
  setup: {
    onEvent: (cb) => { ipcRenderer.on("setup:event", (_e, ev) => cb(ev)); },
    ready: () => ipcRenderer.invoke("setup:ready"),
    start: (opts) => ipcRenderer.invoke("setup:start", opts || {}),
    cancel: () => ipcRenderer.invoke("setup:cancel"),
    openLogs: () => ipcRenderer.invoke("shell:openLogs"),
  },
  update: {
    check: () => ipcRenderer.invoke("update:check"),
    apply: () => ipcRenderer.invoke("update:apply"),
  },
});
