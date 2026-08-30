/**
 * download-runtimes.js - Downloads standalone Python 3.11 and Node.js 20
 * runtimes for Windows, Linux, or macOS.
 *
 * Usage:
 *   node scripts/download-runtimes.js           # current platform
 *   node scripts/download-runtimes.js --win      # Windows
 *   node scripts/download-runtimes.js --linux    # Linux
 *   node scripts/download-runtimes.js --mac      # macOS (auto-detects arm64 vs x64)
 */

import fs from 'fs';
import path from 'path';
import https from 'https';
import http from 'http';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';

const __filename = fileURLToPath(import.meta.url);
const __dirname  = path.dirname(__filename);
const ROOT       = path.join(__dirname, '..');
const BUILD_DIR  = path.join(ROOT, 'build');
const PYTHON_DIR = path.join(BUILD_DIR, 'python-runtime');
const NODE_DIR   = path.join(BUILD_DIR, 'node-runtime');

fs.mkdirSync(PYTHON_DIR, { recursive: true });
fs.mkdirSync(NODE_DIR,   { recursive: true });

const PYTHON_URLS = {
  win32:       'https://github.com/astral-sh/python-build-standalone/releases/download/20250106/cpython-3.11.11%2B20250106-x86_64-pc-windows-msvc-shared-install_only_stripped.tar.gz',
  linux:       'https://github.com/astral-sh/python-build-standalone/releases/download/20250106/cpython-3.11.11%2B20250106-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz',
  darwin_x64:  'https://github.com/astral-sh/python-build-standalone/releases/download/20250106/cpython-3.11.11%2B20250106-x86_64-apple-darwin-install_only_stripped.tar.gz',
  darwin_arm64:'https://github.com/astral-sh/python-build-standalone/releases/download/20250106/cpython-3.11.11%2B20250106-aarch64-apple-darwin-install_only_stripped.tar.gz',
};

const NODE_URLS = {
  win32:       'https://nodejs.org/dist/v20.18.3/node-v20.18.3-win-x64.zip',
  linux:       'https://nodejs.org/dist/v20.18.3/node-v20.18.3-linux-x64.tar.gz',
  darwin_x64:  'https://nodejs.org/dist/v20.18.3/node-v20.18.3-darwin-x64.tar.gz',
  darwin_arm64:'https://nodejs.org/dist/v20.18.3/node-v20.18.3-darwin-arm64.tar.gz',
};

function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    const proto = url.startsWith('https') ? https : http;
    console.log(`[download] Fetching ${url} ...`);
    const req = proto.get(url, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        return downloadFile(res.headers.location, dest).then(resolve).catch(reject);
      }
      if (res.statusCode !== 200) {
        return reject(new Error(`Failed to download ${url}: HTTP ${res.statusCode}`));
      }
      const stream = fs.createWriteStream(dest);
      res.pipe(stream);
      stream.on('finish', () => { stream.close(); resolve(dest); });
      stream.on('error', reject);
    });
    req.on('error', reject);
  });
}

async function setupRuntimesForPlatform(targetPlatform) {
  console.log(`[runtimes] Setting up runtimes for: ${targetPlatform}`);

  // ── Determine URL keys ────────────────────────────────────────────────────
  let pyKey, nodeKey, folderName;
  if (targetPlatform === 'win32' || targetPlatform === 'win') {
    pyKey = 'win32'; nodeKey = 'win32'; folderName = 'win';
  } else if (targetPlatform === 'darwin' || targetPlatform === 'mac') {
    const isArm = process.arch === 'arm64';
    pyKey   = isArm ? 'darwin_arm64' : 'darwin_x64';
    nodeKey = isArm ? 'darwin_arm64' : 'darwin_x64';
    folderName = 'darwin';
  } else {
    pyKey = 'linux'; nodeKey = 'linux'; folderName = 'linux';
  }

  // ── Python runtime ────────────────────────────────────────────────────────
  const pyDestDir = path.join(PYTHON_DIR, folderName);
  const pyExe = (folderName === 'win')
    ? path.join(pyDestDir, 'python', 'python.exe')
    : path.join(pyDestDir, 'python', 'bin', 'python3');

  if (!fs.existsSync(pyExe)) {
    try {
      fs.mkdirSync(pyDestDir, { recursive: true });
      const pyTar = path.join(pyDestDir, 'python.tar.gz');
      await downloadFile(PYTHON_URLS[pyKey], pyTar);
      console.log(`[runtimes] Extracting Python to ${pyDestDir} ...`);
      execSync(`tar -xzf "${pyTar}" -C "${pyDestDir}"`, { stdio: 'inherit' });
      if (fs.existsSync(pyTar)) fs.unlinkSync(pyTar);
      console.log(`[runtimes] Python ready at: ${pyExe}`);
    } catch (err) {
      console.warn(`[runtimes] Python download/unpack error: ${err.message}`);
    }
  } else {
    console.log(`[runtimes] Python already present at: ${pyExe}`);
  }

  // ── Node.js runtime ───────────────────────────────────────────────────────
  const nodeDestDir = path.join(NODE_DIR, folderName);
  const nodeExe = (folderName === 'win')
    ? path.join(nodeDestDir, 'node', 'node.exe')
    : path.join(nodeDestDir, 'node', 'bin', 'node');

  if (!fs.existsSync(nodeExe)) {
    try {
      fs.mkdirSync(nodeDestDir, { recursive: true });
      const nodeUrl  = NODE_URLS[nodeKey];
      const isZip    = nodeUrl.endsWith('.zip');
      const archive  = path.join(nodeDestDir, isZip ? 'node.zip' : 'node.tar.gz');
      await downloadFile(nodeUrl, archive);
      console.log(`[runtimes] Extracting Node.js to ${nodeDestDir} ...`);

      if (isZip) {
        const tmp = path.join(nodeDestDir, 'temp_extract');
        fs.mkdirSync(tmp, { recursive: true });
        execSync(`powershell -Command "Expand-Archive -Path '${archive}' -DestinationPath '${tmp}' -Force"`, { stdio: 'inherit' });
        const inner = path.join(tmp, fs.readdirSync(tmp)[0]);
        const target = path.join(nodeDestDir, 'node');
        if (fs.existsSync(target)) fs.rmSync(target, { recursive: true, force: true });
        fs.renameSync(inner, target);
        fs.rmSync(tmp, { recursive: true, force: true });
        fs.unlinkSync(archive);
      } else {
        execSync(`tar -xzf "${archive}" -C "${nodeDestDir}"`, { stdio: 'inherit' });
        const entries = fs.readdirSync(nodeDestDir).filter(e => e.startsWith('node-v'));
        if (entries.length > 0) {
          const inner  = path.join(nodeDestDir, entries[0]);
          const target = path.join(nodeDestDir, 'node');
          if (fs.existsSync(target)) fs.rmSync(target, { recursive: true, force: true });
          fs.renameSync(inner, target);
        }
        if (fs.existsSync(archive)) fs.unlinkSync(archive);
      }
      console.log(`[runtimes] Node.js ready at: ${nodeExe}`);
    } catch (err) {
      console.warn(`[runtimes] Node.js download/unpack error: ${err.message}`);
    }
  } else {
    console.log(`[runtimes] Node.js already present at: ${nodeExe}`);
  }
}

// ── Determine target from CLI args ─────────────────────────────────────────
const args = process.argv.slice(2);
let target = process.platform;
if (args.includes('--linux')) target = 'linux';
else if (args.includes('--win'))   target = 'win32';
else if (args.includes('--mac'))   target = 'darwin';

setupRuntimesForPlatform(target).catch((err) => {
  console.warn('[runtimes] Failed:', err.message);
});