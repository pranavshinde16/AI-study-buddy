import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  // Reads frontend/.env* (all keys, not just VITE_*); a shell variable of the same name wins.
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = process.env.API_PROXY_TARGET || env.API_PROXY_TARGET || "http://localhost:8000";

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      port: 5173,
      // Forward API calls to the FastAPI server so the browser sees one origin (no CORS, no token in URLs).
      proxy: {
        "/api": apiTarget,
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: false,
    },
  };
});
