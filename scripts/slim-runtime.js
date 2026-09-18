/**
 * slim-runtime.js — Slims bundled runtimes by removing caches, tests, and heavy non-essential packages.
 *
 * Pre-packaging step for Phase 10.16-FINAL to achieve <= 350MB Windows installer target.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.join(__dirname, '..');
const PYTHON_DIR = path.join(ROOT, 'resources', 'python');
const SITE_PACKAGES = path.join(PYTHON_DIR, 'Lib', 'site-packages');
const BACKEND_INTERNAL = path.join(ROOT, 'backend', 'dist', 'backend', '_internal');

function getDirSize(dir) {
  if (!fs.existsSync(dir)) return 0;
  let total = 0;
  function walk(d) {
    let entries;
    try {
      entries = fs.readdirSync(d, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const full = path.join(d, e.name);
      if (e.isDirectory()) {
        walk(full);
      } else if (e.isFile()) {
        try {
          total += fs.statSync(full).size;
        } catch {}
      }
    }
  }
  walk(dir);
  return total;
}

function removePath(p) {
  if (fs.existsSync(p)) {
    try {
      fs.rmSync(p, { recursive: true, force: true });
      return true;
    } catch (err) {
      console.warn(`[slim] Failed to remove ${p}: ${err.message}`);
    }
  }
  return false;
}

console.log('═══════════════════════════════════════════════════════════════════');
console.log('SLIM RUNTIME: OPTIMIZING BUNDLED ASSETS FOR COMPRESSION');
console.log('═══════════════════════════════════════════════════════════════════');

const initialSize = getDirSize(PYTHON_DIR);
console.log(`Initial resources/python size: ${(initialSize / 1024 / 1024).toFixed(1)} MB`);

// 1. Remove __pycache__ and *.pyc throughout resources/python
console.log('[slim] Pruning __pycache__ and compiled bytecode (*.pyc)...');
function pruneCachesAndTests(dir) {
  if (!fs.existsSync(dir)) return;
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const e of entries) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) {
      const lower = e.name.toLowerCase();
      if (lower === '__pycache__' || lower === 'tests' || lower === 'test') {
        removePath(full);
        continue;
      }
      pruneCachesAndTests(full);
    } else if (e.isFile()) {
      if (e.name.endsWith('.pyc') || e.name.endsWith('.pyo')) {
        removePath(full);
      }
    }
  }
}
pruneCachesAndTests(PYTHON_DIR);

// 2. Remove heavy non-essential packages in resources/python/Lib/site-packages
// Heavy local embedding (torch/transformers/scipy) is optional post-install; default RAG = lightweight lexical / onnx
const HEAVY_PACKAGES_TO_PRUNE = [
  'torch',
  'torchaudio',
  'torchvision',
  'scipy',
  'scipy.libs',
  'sympy',
  'playwright',
  'kubernetes',
  'ctranslate2',
  'av.libs',
  'sklearn',
  'fitz_new',
  'nltk',
  'pip',
  '_distutils_hack',
];

if (fs.existsSync(SITE_PACKAGES)) {
  console.log('[slim] Pruning heavy non-essential site-packages...');
  for (const pkg of HEAVY_PACKAGES_TO_PRUNE) {
    const pkgPath = path.join(SITE_PACKAGES, pkg);
    if (fs.existsSync(pkgPath)) {
      const sz = getDirSize(pkgPath);
      removePath(pkgPath);
      console.log(`  - Pruned ${pkg} (${(sz / 1024 / 1024).toFixed(1)} MB)`);
    }
    // Also remove any matching .dist-info
    try {
      const entries = fs.readdirSync(SITE_PACKAGES);
      for (const e of entries) {
        if (e.toLowerCase().startsWith(pkg.toLowerCase() + '-') && e.endsWith('.dist-info')) {
          removePath(path.join(SITE_PACKAGES, e));
        }
      }
    } catch {}
  }
}

// 3. Prune heavy unneeded packages in backend/dist/backend/_internal if present
if (fs.existsSync(BACKEND_INTERNAL)) {
  console.log('[slim] Pruning unused binary libs in backend/dist/backend/_internal...');
  const BACKEND_PRUNE = [
    'cv2',
    'googleapiclient',
    'playwright',
    'ctranslate2',
    'av.libs',
    'scipy',
    'scipy.libs',
  ];
  for (const item of BACKEND_PRUNE) {
    const itemPath = path.join(BACKEND_INTERNAL, item);
    if (fs.existsSync(itemPath)) {
      const sz = getDirSize(itemPath);
      removePath(itemPath);
      console.log(`  - Pruned _internal/${item} (${(sz / 1024 / 1024).toFixed(1)} MB)`);
    }
  }
  pruneCachesAndTests(BACKEND_INTERNAL);
}

const finalSize = getDirSize(PYTHON_DIR);
console.log('───────────────────────────────────────────────────────────────────');
console.log(`Final resources/python size: ${(finalSize / 1024 / 1024).toFixed(1)} MB`);
console.log(`Space saved: ${((initialSize - finalSize) / 1024 / 1024).toFixed(1)} MB`);
console.log('═══════════════════════════════════════════════════════════════════');
