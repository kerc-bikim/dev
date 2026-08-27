import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 브라우저는 기록계와 InfluxDB 에 직접 접속하지 않는다. 언제나 백엔드 API 만 호출한다.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/healthz": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/readyz": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
