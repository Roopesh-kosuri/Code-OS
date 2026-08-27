import path from "path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  plugins: [react()],
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
