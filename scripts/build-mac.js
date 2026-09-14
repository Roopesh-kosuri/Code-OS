#!/usr/bin/env node
/**
 * scripts/build-mac.js
 *
 * AUD-015 / Phase 10.5: Credential-Graded macOS Build Runner
 * - If Apple signing credentials exist: builds signed + notarized artifacts.
 * - If credentials are missing: marks artifact suffix as '-UNSIGNED-DEV' so
 *   unsigned builds are transparently identified and blocked from release channel.
 */

import { execSync } from "node:child_process";

const hasCreds = Boolean(
  process.env.CSC_LINK ||
  (process.env.APPLE_ID && process.env.APPLE_TEAM_ID && process.env.APPLE_APP_SPECIFIC_PASSWORD)
);

if (!hasCreds) {
  process.env.MAC_BUILD_SUFFIX = "-UNSIGNED-DEV";
  console.log("[build:mac] No Apple Developer ID credentials in environment.");
  console.log("[build:mac] Applying credential-grade label: artifactName will contain '-UNSIGNED-DEV'.");
} else {
  process.env.MAC_BUILD_SUFFIX = "";
  console.log("[build:mac] Apple Developer ID credentials detected.");
  console.log("[build:mac] Building signed, hardened-runtime, and notarized macOS artifacts.");
}

try {
  console.log("[build:mac] Running production pre-build (vite, electron, backend-exe)...");
  execSync("npm run build", { stdio: "inherit" });

  console.log("[build:mac] Running electron-builder for macOS (dmg, zip)...");
  execSync("npx electron-builder --mac", { stdio: "inherit", env: process.env });

  console.log("[build:mac] macOS build completed successfully.");
} catch (err) {
  console.error("[build:mac] Build failed:", err.message);
  process.exit(1);
}
