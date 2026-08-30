/**
 * preflight.js - Pre-packaging preflight check.
 *
 * Verifies that all required build artefacts exist before electron-builder
 * is invoked.  Fails fast with a clear, actionable message so the CI log
 * immediately points to the root cause instead of a cryptic builder error.
 *
 * Run automatically via the "package" script:
 *   npm run package => npm run build && node scripts/preflight.js && electron-builder
 *
 * Exit 0 = all good.  Exit 1 = missing artefact(s).
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');

const errors = [];

// 1. Frontend bundle
const distIndex = path.join(ROOT, 'dist', 'index.html');
if (!fs.existsSync(distIndex)) {
  errors.push(`Missing: ${distIndex}  →  run 'npm run build:vite' first`);
}

// 2. Compiled Electron main
const electronMain = path.join(ROOT, 'dist-electron', 'main.js');
if (!fs.existsSync(electronMain)) {
  errors.push(`Missing: ${electronMain}  →  run 'npm run build:electron' first`);
}

// 3. PyInstaller backend binary (platform-specific)
const exeName = process.platform === 'win32' ? 'backend-server.exe' : 'backend-server';
const backendBin = path.join(ROOT, 'backend-dist', exeName);
if (!fs.existsSync(backendBin)) {
  errors.push(`Missing: ${backendBin}  →  run 'npm run build:backend-exe' first`);
}

// 4. Bundled Python runtime for current platform
const platformFolder =
  process.platform === 'win32' ? 'win' :
  process.platform === 'darwin' ? 'darwin' : 'linux';
const pyExe = process.platform === 'win32'
  ? path.join(ROOT, 'build', 'python-runtime', 'win', 'python', 'python.exe')
  : path.join(ROOT, 'build', 'python-runtime', platformFolder, 'python', 'bin', 'python3');
if (!fs.existsSync(pyExe)) {
  errors.push(`Missing bundled Python: ${pyExe}  →  run 'npm run download:runtimes' first`);
}

// 5. Bundled Node runtime for current platform
const nodeExe = process.platform === 'win32'
  ? path.join(ROOT, 'build', 'node-runtime', 'win', 'node', 'node.exe')
  : path.join(ROOT, 'build', 'node-runtime', platformFolder, 'node', 'bin', 'node');
if (!fs.existsSync(nodeExe)) {
  errors.push(`Missing bundled Node.js: ${nodeExe}  →  run 'npm run download:runtimes' first`);
}

if (errors.length > 0) {
  console.error('\n[preflight] PACKAGING ABORTED — missing artefacts:\n');
  for (const e of errors) console.error(`  ✗ ${e}`);
  console.error('\nFix the above, then re-run: npm run package\n');
  process.exit(1);
}

console.log('[preflight] All artefacts present — proceeding with electron-builder.');