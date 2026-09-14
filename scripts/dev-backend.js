import { spawn, execSync } from "node:child_process";
import path from "node:path";
import fs from "node:fs";

function getPythonVersion(cmd) {
  try {
    const output = execSync(`${cmd} --version`, { stdio: "pipe" }).toString().trim();
    const match = output.match(/Python\s+([0-9\.]+)/i);
    if (match && match[1]) {
      return match[1];
    }
  } catch (e) {
    // executable not found or failed
  }
  return null;
}

function parseSemver(versionStr) {
  const parts = versionStr.split(".").map(Number);
  return {
    major: parts[0] || 0,
    minor: parts[1] || 0,
    patch: parts[2] || 0
  };
}

function isVersionSupported(versionStr) {
  if (!versionStr) return false;
  const ver = parseSemver(versionStr);
  if (ver.major > 3) return true;
  if (ver.major === 3 && ver.minor >= 11) return true;
  return false;
}

function findPython() {
  const candidates = ["python3", "python"];
  for (const cmd of candidates) {
    const version = getPythonVersion(cmd);
    if (version && isVersionSupported(version)) {
      console.log(`Found supported Python version ${version} via command: ${cmd}`);
      return cmd;
    } else if (version) {
      console.warn(`Warning: Found Python ${version} via '${cmd}', but version >= 3.11 is required.`);
    }
  }
  console.error("Error: A compatible Python interpreter (>= 3.11) was not found in PATH.");
  console.error("Please install Python 3.11 or newer and add it to your environment variables.");
  process.exit(1);
}

const pythonCmd = findPython();
const backendDir = path.resolve("backend");
const args = ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"];

let shouldRestart = true;
let currentProc = null;

function startBackend() {
  console.log("[dev:backend] Spawning Uvicorn backend supervisor...");
  const tiktokenDir = path.resolve("resources", "tiktoken");
  const spawnEnv = { ...process.env, PYTHONPATH: backendDir };
  if (fs.existsSync(tiktokenDir)) {
    spawnEnv.TIKTOKEN_CACHE_DIR = tiktokenDir;
  }
  currentProc = spawn(pythonCmd, args, {
    stdio: "inherit",
    cwd: backendDir,
    env: spawnEnv
  });

  currentProc.on("exit", (code, signal) => {
    console.warn(`[dev:backend] Process exited with code ${code}, signal ${signal}.`);
    if (shouldRestart) {
      console.log("[dev:backend] Restarting backend in 1000ms...");
      setTimeout(startBackend, 1000);
    }
  });

  currentProc.on("error", (err) => {
    console.error("[dev:backend] Spawn error:", err);
  });
}

function killCurrent() {
  shouldRestart = false;
  if (currentProc && currentProc.pid) {
    if (process.platform === "win32") {
      try {
        execSync(`taskkill /F /T /PID ${currentProc.pid}`, { stdio: "ignore" });
      } catch {}
    } else {
      try {
        currentProc.kill("SIGTERM");
      } catch {}
    }
  }
}

process.on("SIGINT", () => {
  killCurrent();
  process.exit(0);
});

process.on("SIGTERM", () => {
  killCurrent();
  process.exit(0);
});

process.on("exit", () => {
  killCurrent();
});

startBackend();
