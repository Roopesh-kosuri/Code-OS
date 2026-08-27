/**
 * download-runtimes.js - Downloads and unpacks standalone Python 3.11 and Node.js 20 runtimes
 *
 * Prepares zero-dependency bundled runtimes for Windows, Linux, and macOS.
 */

import fs from 'fs';
import path from 'path';
import https from 'https';
import http from 'http';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.join(__dirname, '..');

const BUILD_DIR = path.join(ROOT, 'build');
const PYTHON_DIR = path.join(BUILD_DIR, 'python-runtime');
const NODE_DIR = path.join(BUILD_DIR, 'node-runtime');

// Ensure base directories exist
fs.mkdirSync(PYTHON_DIR, { recursive: true });
fs.mkdirSync(NODE_DIR, { recursive: true });

const PYTHON_URLS = {
  win32: 'https://github.com/astral-sh/python-build-standalone/releases/download/20250106/cpython-3.11.11%2B20250106-x86_64-pc-windows-msvc-shared-install_only_stripped.tar.gz',
  linux: 'https://github.com/astral-sh/python-build-standalone/releases/download/20250106/cpython-3.11.11%2B20250106-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz',
  darwin_x64: 'https://github.com/astral-sh/python-build-standalone/releases/download/20250106/cpython-3.11.11%2B20250106-x86_64-apple-darwin-install_only_stripped.tar.gz',
  darwin_arm64: 'https://github.com/astral-sh/python-build-standalone/releases/download/20250106/cpython-3.11.11%2B20250106-aarch64-apple-darwin-install_only_stripped.tar.gz',
};

const NODE_URLS = {
  win32: 'https://nodejs.org/dist/v20.18.3/node-v20.18.3-win-x64.zip',
  linux: 'https://nodejs.org/dist/v20.18.3/node-v20.18.3-linux-x64.tar.gz',
  darwin_x64: 'https://nodejs.org/dist/v20.18.3/node-v20.18.3-darwin-x64.tar.gz',
  darwin_arm64: 'https://nodejs.org/dist/v20.18.3/node-v20.18.3-darwin-arm64.tar.gz',
};

function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    const proto = url.startsWith('https') ? https : http;
    console.log(`[download] Fetching ${url} ...`);
    const req = proto.get(url, (res) => {
      // Handle redirects (e.g. GitHub releases)
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        return downloadFile(res.headers.location, dest).then(resolve).catch(reject);
      }
      if (res.statusCode !== 200) {
        return reject(new Error(`Failed to download ${url}: HTTP ${res.statusCode}`));
      }
      const fileStream = fs.createWriteStream(dest);
      res.pipe(fileStream);
      fileStream.on('finish', () => {
        fileStream.close();
        resolve(dest);
      });
      fileStream.on('error', reject);
    });
    req.on('error', reject);
  });
}

async function setupRuntimesForPlatform(targetPlatform) {
  console.log(`[runtimes] Setting up runtimes for target platform: ${targetPlatform}...`);

  // 1. Python runtime
  const pyDestDir = path.join(PYTHON_DIR, targetPlatform === 'win32' || targetPlatform === 'win' ? 'win' : 'linux');
  const pyExe = (targetPlatform === 'win32' || targetPlatform === 'win')
    ? path.join(pyDestDir, 'python', 'python.exe')
    : path.join(pyDestDir, 'python', 'bin', 'python3');

  if (!fs.existsSync(pyExe)) {
    try {
      fs.mkdirSync(pyDestDir, { recursive: true });
      const pyUrl = (targetPlatform === 'win32' || targetPlatform === 'win') ? PYTHON_URLS.win32 : PYTHON_URLS.linux;
      const pyTar = path.join(pyDestDir, 'python.tar.gz');
      await downloadFile(pyUrl, pyTar);
      console.log(`[runtimes] Extracting Python to ${pyDestDir} ...`);
      execSync(`tar -xzf "${pyTar}" -C "${pyDestDir}"`, { stdio: 'inherit' });
      if (fs.existsSync(pyTar)) fs.unlinkSync(pyTar);
      console.log(`[runtimes] Python ready at: ${pyExe}`);
    } catch (err) {
      console.warn(`[runtimes] Warning: Python download/unpack error: ${err.message}`);
    }
  } else {
    console.log(`[runtimes] Python already present at: ${pyExe}`);
  }

  // 2. Node.js runtime
  const nodeDestDir = path.join(NODE_DIR, targetPlatform === 'win32' || targetPlatform === 'win' ? 'win' : 'linux');
  const nodeExe = (targetPlatform === 'win32' || targetPlatform === 'win')
    ? path.join(nodeDestDir, 'node', 'node.exe')
    : path.join(nodeDestDir, 'node', 'bin', 'node');

  if (!fs.existsSync(nodeExe)) {
    try {
      fs.mkdirSync(nodeDestDir, { recursive: true });
      const nodeUrl = (targetPlatform === 'win32' || targetPlatform === 'win') ? NODE_URLS.win32 : NODE_URLS.linux;
      const isZip = nodeUrl.endsWith('.zip');
      const archiveFile = path.join(nodeDestDir, isZip ? 'node.zip' : 'node.tar.gz');
      await downloadFile(nodeUrl, archiveFile);
      console.log(`[runtimes] Extracting Node.js to ${nodeDestDir} ...`);

      if (isZip) {
        const tempExtract = path.join(nodeDestDir, 'temp_extract');
        fs.mkdirSync(tempExtract, { recursive: true });
        execSync(`powershell -Command "Expand-Archive -Path '${archiveFile}' -DestinationPath '${tempExtract}' -Force"`, { stdio: 'inherit' });
        const entries = fs.readdirSync(tempExtract);
        const inner = path.join(tempExtract, entries[0]);
        const targetNodeDir = path.join(nodeDestDir, 'node');
        if (fs.existsSync(targetNodeDir)) fs.rmSync(targetNodeDir, { recursive: true, force: true });
        fs.renameSync(inner, targetNodeDir);
        fs.rmSync(tempExtract, { recursive: true, force: true });
        fs.unlinkSync(archiveFile);
      } else {
        execSync(`tar -xzf "${archiveFile}" -C "${nodeDestDir}"`, { stdio: 'inherit' });
        const entries = fs.readdirSync(nodeDestDir).filter(e => e.startsWith('node-v'));
        if (entries.length > 0) {
          const inner = path.join(nodeDestDir, entries[0]);
          const targetNodeDir = path.join(nodeDestDir, 'node');
          if (fs.existsSync(targetNodeDir)) fs.rmSync(targetNodeDir, { recursive: true, force: true });
          fs.renameSync(inner, targetNodeDir);
        }
        if (fs.existsSync(archiveFile)) fs.unlinkSync(archiveFile);
      }
      console.log(`[runtimes] Node.js ready at: ${nodeExe}`);
    } catch (err) {
      console.warn(`[runtimes] Warning: Node.js download/unpack error: ${err.message}`);
    }
  } else {
    console.log(`[runtimes] Node.js already present at: ${nodeExe}`);
  }
}

const args = process.argv.slice(2);
let target = process.platform;
if (args.includes('--linux')) target = 'linux';
else if (args.includes('--win')) target = 'win32';

setupRuntimesForPlatform(target).catch((err) => {
  console.warn('[runtimes] Failed to setup runtimes:', err.message);
});
