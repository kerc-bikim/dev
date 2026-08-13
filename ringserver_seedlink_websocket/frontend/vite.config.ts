import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    fs: { allow: [".."] },
    host: true,
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8787", changeOrigin: true },
      "/ringserver": {
        target: "http://127.0.0.1:8787",
        changeOrigin: true,
        ws: true,
      },
      "/fdsnws": { target: "http://127.0.0.1:8787", changeOrigin: true },
    },
  },
});
