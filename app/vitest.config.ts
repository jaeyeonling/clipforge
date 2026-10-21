import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// 화면 단위 테스트: jsdom 위에서 순수 로직과 작은 컴포넌트를 검증한다. 엔진·Electron 은 띄우지 않는다.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
  },
});
