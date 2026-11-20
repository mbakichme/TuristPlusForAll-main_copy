import path from "path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// U sandbox-u (APP_PORT postoji) browser pristupa preko HTTPS preview proxy-ja
// na 443, pa HMR websocket mora ići na wss://<host>:443, ne na ws://<host>:<APP_PORT>.
const uSandboxu = !!process.env.APP_PORT;

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    strictPort: true,
    allowedHosts: true,
    hmr: uSandboxu ? { protocol: "wss", clientPort: 443 } : undefined,
    proxy: {
      "/api": `http://localhost:${process.env.VITE_BACKEND_PORT || 3101}`,
    },
    watch: {
      ignored: [
        "**/node_modules/**",
        "**/.venv/**",
        "**/.git/**",
        "**/dist/**",
        "**/__pycache__/**",
      ],
    },
  },
});
