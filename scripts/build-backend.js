/**
 * build-backend.js — Compiles the Python FastAPI backend into a standalone
 * executable using PyInstaller so end-users do NOT need Python installed.
 *
 * Called automatically during `npm run build` before electron-builder.
 * Output: backend-dist/backend-server.exe (Windows)
 *         backend-dist/backend-server     (Linux/Mac)
 *
 * NOTE: PyInstaller often exits with code 1 even on successful builds when
 * it encounters non-fatal import warnings. We treat any exit code as OK as
 * long as the binary exists after the run.
 */

import { spawnSync } from 'child_process';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const ROOT = path.join(__dirname, '..');
const DIST_DIR = path.join(ROOT, 'backend-dist');
const exeName = process.platform === 'win32' ? 'backend-server.exe' : 'backend-server';
const outputPath = path.join(DIST_DIR, exeName);

// Ensure output directory exists
if (!fs.existsSync(DIST_DIR)) {
  fs.mkdirSync(DIST_DIR, { recursive: true });
}

console.log('[build-backend] Starting PyInstaller backend compilation...');

function runPyInstaller(pythonCmd) {
  const result = spawnSync(
    pythonCmd,
    ['-m', 'PyInstaller', 'backend-server.spec',
     '--distpath', 'backend-dist',
     '--workpath', 'backend-build',
     '--clean', '--noconfirm'],
    {
      cwd: ROOT,
      stdio: 'inherit',
      env: { ...process.env },
      // Don't throw on non-zero exit — PyInstaller exits 1 on warnings
    }
  );
  // spawnSync returns null for status if process was killed
  return result.status !== null;
}

// Try python first, then python3
const ran = runPyInstaller('python') || runPyInstaller('python3');

if (!ran) {
  console.error('[build-backend] Could not spawn Python. Ensure Python 3.11+ is in PATH.');
}

// Check if binary was actually produced (the real success signal)
if (fs.existsSync(outputPath)) {
  const sizeMB = (fs.statSync(outputPath).size / 1024 / 1024).toFixed(1);
  console.log(`[build-backend] ✓ Compiled successfully: ${outputPath} (${sizeMB} MB)`);
} else {
  console.warn('[build-backend] WARNING: Binary not found at', outputPath);
  console.warn('[build-backend] Packaged app will fall back to system Python.');
  // Not a fatal error — packaged app falls back to system Python
}
