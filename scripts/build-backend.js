/**
 * build-backend.js — Compiles the Python FastAPI backend into a standalone
 * directory package using PyInstaller (--onedir mode) with watchdog supervisor.
 *
 * Called automatically during `npm run build` before electron-builder.
 * Output: backend/dist/backend/watchdog_launcher.exe (Windows)
 *         backend/dist/backend/watchdog_launcher     (Linux/Mac)
 */

import { spawnSync } from 'child_process';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const ROOT = path.join(__dirname, '..');
const BACKEND_DIR = path.join(ROOT, 'backend');
const DIST_DIR = path.join(BACKEND_DIR, 'dist', 'backend');
const exeName = process.platform === 'win32' ? 'watchdog_launcher.exe' : 'watchdog_launcher';
const outputPath = path.join(DIST_DIR, exeName);

console.log('[build-backend] Starting PyInstaller --onedir backend compilation...');
console.log(`[build-backend] Target: ${outputPath}`);

function runPyInstaller(pythonCmd) {
  try {
    const result = spawnSync(
      pythonCmd,
      [
        '-m', 'PyInstaller', 'build.spec',
        '--distpath', 'dist',
        '--workpath', 'build',
        '--clean', '--noconfirm',
      ],
      {
        cwd: BACKEND_DIR,
        stdio: 'inherit',
        env: { ...process.env },
      }
    );
    return result.status !== null;
  } catch (err) {
    return false;
  }
}

// Try py first on Windows, then python, then python3
const commands = process.platform === 'win32' ? ['py', 'python', 'python3'] : ['python3', 'python'];
let ran = false;

for (const cmd of commands) {
  console.log(`[build-backend] Attempting build with '${cmd}'...`);
  ran = runPyInstaller(cmd);
  if (ran && fs.existsSync(outputPath)) {
    break;
  }
}

if (!ran && !fs.existsSync(outputPath)) {
  console.error('[build-backend] Could not spawn Python. Ensure Python 3.11+ is in PATH.');
}

// Check if binary was actually produced
if (fs.existsSync(outputPath)) {
  const sizeMB = (fs.statSync(outputPath).size / 1024 / 1024).toFixed(1);
  console.log(`[build-backend] ✓ Compiled successfully: ${outputPath} (${sizeMB} MB)`);
} else {
  console.warn('[build-backend] WARNING: Executable not found at', outputPath);
}
