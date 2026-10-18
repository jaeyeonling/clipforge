// 렌더러(React 화면)에 노출하는 최소 API. 화면은 지금 HTTP/WS 로 엔진과 직접 대화하므로 정보성 값만 준다.
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("clipforgeShell", {
  platform: process.platform,
  versions: { electron: process.versions.electron, node: process.versions.node, chrome: process.versions.chrome },
});
