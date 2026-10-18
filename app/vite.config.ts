import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발: vite 가 화면을 띄우고 /api·/media·/ws 는 엔진(127.0.0.1:8765)으로 프록시.
// 배포: `npm run build` → dist/ 를 엔진이 정적으로 서빙 (project.ui_dir). Electron 껍데기도 같은 dist 를 로드한다.
const ENGINE = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    host: "127.0.0.1",
    proxy: {
      "/api": ENGINE,
      "/media": ENGINE,
      "/ws": { target: ENGINE.replace("http", "ws"), ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false, target: "es2022" },
});
