/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

// Dev server is loopback-only. /api and /health|/ready are proxied to the
// backend (D2) at DD_API_TARGET, default http://127.0.0.1:8000.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.DD_API_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [vue()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": { target, changeOrigin: false },
        "/health": { target },
        "/ready": { target },
      },
    },
    preview: { host: "127.0.0.1", port: 4173, strictPort: true },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["src/test/setup.ts"],
      include: ["src/**/*.test.{ts,tsx}"],
    },
  };
});
