import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 중에는 /api 요청을 내 컴퓨터의 서버(FastAPI)로 넘겨줍니다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": process.env.VITE_PROXY_TARGET || "http://localhost:8000",
    },
  },
});
