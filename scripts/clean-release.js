/**
 * clean-release.js — Deletes stale release and installer artifacts.
 *
 * Usage:
 *   node scripts/clean-release.js              # Pre-build: delete all existing installer packages in release/
 *   node scripts/clean-release.js --prune-stale # Post-build: delete artifacts not matching current version
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.join(__dirname, '..');
const RELEASE_DIR = path.join(ROOT, 'release');
const DIST_DIR = path.join(ROOT, 'dist');

const pkgPath = path.join(ROOT, 'package.json');
const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
const currentVersion = pkg.version || '5.0.0';

const args = process.argv.slice(2);
const isPruneStale = args.includes('--prune-stale');

const INSTALLER_EXTENSIONS = [
  '.exe',
  '.dmg',
  '.appimage',
  '.deb',
  '.zip',
  '.tar.gz',
  '.blockmap',
  '.yml',
  '.yaml',
];

function isInstallerFile(filename) {
  const lower = filename.toLowerCase();
  return INSTALLER_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

function cleanDirectory(dir, pruneOnly = false) {
  if (!fs.existsSync(dir)) return;

  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);

    if (entry.isDirectory()) {
      // Skip win-unpacked, mac, linux-unpacked unless doing a full prebuild clean
      if (!pruneOnly && (entry.name.endsWith('-unpacked') || entry.name === 'mac')) {
        try {
          fs.rmSync(fullPath, { recursive: true, force: true });
          console.log(`[clean-release] Removed unpacked directory: ${entry.name}`);
        } catch (err) {
          console.warn(`[clean-release] Could not remove directory ${entry.name}: ${err.message}`);
        }
      }
      continue;
    }

    if (entry.isFile() && isInstallerFile(entry.name)) {
      if (pruneOnly) {
        // Post-build mode: keep files that contain the current version string
        if (entry.name.includes(currentVersion)) {
          console.log(`[clean-release] Retaining current version artifact: ${entry.name}`);
          continue;
        }
        console.log(`[clean-release] Pruning stale version artifact: ${entry.name}`);
      } else {
        console.log(`[clean-release] Removing prebuild artifact: ${entry.name}`);
      }

      try {
        fs.unlinkSync(fullPath);
      } catch (err) {
        console.warn(`[clean-release] Failed to delete ${entry.name}: ${err.message}`);
      }
    }
  }
}

console.log(`[clean-release] Mode: ${isPruneStale ? 'Prune Stale Artifacts' : 'Full Pre-build Clean'} (Current version: ${currentVersion})`);
if (!isPruneStale) {
  if (fs.existsSync(RELEASE_DIR)) {
    fs.rmSync(RELEASE_DIR, { recursive: true, force: true });
    console.log(`[clean-release] Removed ${RELEASE_DIR}`);
  }
  if (fs.existsSync(DIST_DIR)) {
    fs.rmSync(DIST_DIR, { recursive: true, force: true });
    console.log(`[clean-release] Removed ${DIST_DIR}`);
  }
} else {
  cleanDirectory(RELEASE_DIR, true);
}
console.log('[clean-release] Clean complete.');
