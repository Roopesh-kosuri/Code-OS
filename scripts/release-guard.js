#!/usr/bin/env node
/**
 * scripts/release-guard.js
 *
 * AUD-015 / Phase 10.5: Release Channel Guard Script
 *
 * Enforces that no unsigned macOS artifacts (or artifacts labeled 'UNSIGNED-DEV')
 * are ever published to the 'release' channel.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_DIR = path.resolve(__dirname, "..");

export function hasMacSigningCredentials() {
  return Boolean(
    process.env.CSC_LINK ||
    (process.env.APPLE_ID && process.env.APPLE_TEAM_ID && process.env.APPLE_APP_SPECIFIC_PASSWORD)
  );
}

export function validateReleaseArtifacts(targetDir, options = {}) {
  const channel = (options.channel || process.env.CHANNEL || "release").toLowerCase();
  const dir = path.resolve(targetDir || path.resolve(ROOT_DIR, "release"));

  console.log(`[release-guard] Inspecting artifacts in: ${dir}`);
  console.log(`[release-guard] Target channel: '${channel}'`);

  if (!fs.existsSync(dir)) {
    console.warn(`[release-guard] Target directory does not exist: ${dir}`);
    return { allowed: channel !== "release", error: `Directory not found: ${dir}` };
  }

  const entries = fs.readdirSync(dir, { recursive: true })
    .map(f => typeof f === "string" ? f : f.name);

  const macArtifacts = entries.filter(f => {
    const ext = path.extname(f).toLowerCase();
    const isMacExt = [".dmg", ".zip"].includes(ext) || f.endsWith(".app");
    const isMacName = f.toLowerCase().includes("mac") || f.toLowerCase().includes("darwin") || ext === ".dmg" || f.endsWith(".app");
    return isMacExt || isMacName;
  });

  if (macArtifacts.length === 0) {
    console.log("[release-guard] No macOS artifacts found in target directory.");
    return { allowed: true, count: 0 };
  }

  const hasCreds = hasMacSigningCredentials();
  const unsignedArtifacts = [];

  for (const file of macArtifacts) {
    const baseName = path.basename(file);
    const isUnsignedDevLabel = baseName.toUpperCase().includes("UNSIGNED-DEV");

    if (isUnsignedDevLabel || (!hasCreds && channel === "release")) {
      unsignedArtifacts.push({
        file: baseName,
        reason: isUnsignedDevLabel ? "Labeled as UNSIGNED-DEV" : "Signing credentials missing",
      });
    }
  }

  if (unsignedArtifacts.length > 0) {
    if (channel === "release") {
      const details = unsignedArtifacts.map(u => `  - ${u.file} (${u.reason})`).join("\n");
      const errorMsg = `Release guard BLOCKED publish on channel 'release':\n${details}\nUnsigned macOS builds must never be published to the release channel.`;
      console.error(`[release-guard] ERROR: ${errorMsg}`);
      return {
        allowed: false,
        error: errorMsg,
        unsignedArtifacts,
      };
    } else {
      console.warn(`[release-guard] WARNING: Unsigned macOS artifacts detected on non-release channel '${channel}'. Allowed for development/testing.`);
      return {
        allowed: true,
        channel,
        unsignedArtifacts,
      };
    }
  }

  console.log(`[release-guard] PASS: All ${macArtifacts.length} macOS release artifacts verified compliant for channel '${channel}'.`);
  return { allowed: true, count: macArtifacts.length };
}

// CLI Execution
if (process.argv[1] && process.argv[1].endsWith("release-guard.js")) {
  const args = process.argv.slice(2);
  let channel = "release";
  let targetDir = path.resolve(ROOT_DIR, "release");

  for (const arg of args) {
    if (arg.startsWith("--channel=")) {
      channel = arg.split("=")[1];
    } else if (!arg.startsWith("--")) {
      targetDir = path.resolve(arg);
    }
  }

  const result = validateReleaseArtifacts(targetDir, { channel });
  if (!result.allowed) {
    process.exit(1);
  }
  process.exit(0);
}
