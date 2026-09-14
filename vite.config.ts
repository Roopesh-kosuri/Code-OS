import path from "path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { execSync } from "child_process";

let buildHash = "5cfa46d";
try {
  buildHash = execSync("git rev-parse --short HEAD").toString().trim();
} catch {}

export default defineConfig({
  base: "./",
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify("5.0.0"),
    __BUILD_HASH__: JSON.stringify(buildHash),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // Serve Monaco editor workers from node_modules as static assets.
  publicDir: "public",
  server: {
    host: "127.0.0.1",
    port: 5176,
    strictPort: false,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
    fs: {
      allow: ["..", path.resolve(__dirname, "node_modules/monaco-editor")],
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 2000,
  },
});
