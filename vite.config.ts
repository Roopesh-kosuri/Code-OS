import path from "path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // Serve Monaco editor workers from node_modules as static assets.
  // This prevents @monaco-editor/react from trying to fetch them from
  // the jsdelivr CDN (which fails in Electron and offline environments).
  publicDir: "public",
  server: {
    host: "127.0.0.1",
    port: 5176,
    strictPort: true,
    fs: {
      // Allow Vite dev server to serve files from node_modules
      allow: ["..", path.resolve(__dirname, "node_modules/monaco-editor")],
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
