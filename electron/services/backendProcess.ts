import { ChildProcessWithoutNullStreams, spawn, execSync } from "node:child_process";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import { app, dialog } from "electron";

const isDev = Boolean(!app || !app.isPackaged);

function getUserDataPath(): string {
  try {
    return app?.getPath ? app.getPath("userData") : path.join(os.homedir(), ".code_os");
  } catch {
    return path.join(os.homedir(), ".code_os");
  }
}

function getAppPathSafe(): string {
  try {
    return app?.getAppPath ? app.getAppPath() : process.cwd();
  } catch {
    return process.cwd();
  }
}

export function killPort(port: number = 8000): void {
  try {
    if (process.platform === "win32") {
      const netstatOutput = execSync("netstat -ano -p tcp", { stdio: "pipe" }).toString();
      const pidsToKill = new Set<string>();
      for (const line of netstatOutput.split(/\r?\n/)) {
        if (!line.includes("LISTENING")) continue;
        if (line.includes(`:${port} `) || line.includes(`:${port}\t`)) {
          const parts = line.trim().split(/\s+/);
          const pid = parts[parts.length - 1];
          if (pid && pid !== "0" && pid !== String(process.pid)) {
            pidsToKill.add(pid);
          }
        }
      }
      for (const pid of pidsToKill) {
        try {
          execSync(`taskkill /F /T /PID ${pid}`, { stdio: "ignore" });
        } catch {}
      }
    } else {
      const pids = execSync(`lsof -ti :${port}`, { stdio: "pipe" }).toString().trim();
      if (pids) {
        execSync(`kill -9 ${pids.split(/\s+/).join(" ")}`, { stdio: "ignore" });
      }
    }
  } catch {}
}

export interface BackendSpawnOptions {
  cwd?: string;
  env?: NodeJS.ProcessEnv;
  windowsHide: boolean;
  stdio: ["ignore", "pipe", "pipe"];
  creationFlags?: number;
}

export function buildSpawnOptions(
  platform: string = process.platform,
  env?: NodeJS.ProcessEnv,
  cwd?: string
): BackendSpawnOptions {
  const options: BackendSpawnOptions = {
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  };
  if (cwd) options.cwd = cwd;
  if (env) options.env = env;
  if (platform === "win32") {
    options.creationFlags = 0x08000000;
  }
  return options;
}

function getPythonVersion(cmd: string): string | null {
  try {
    const output = execSync(`${cmd} --version`, { stdio: "pipe", windowsHide: true }).toString().trim();
    const match = output.match(/Python\s+([0-9\.]+)/i);
    if (match && match[1]) return match[1];
  } catch { /* not found */ }
  return null;
}

function parseSemver(v: string) {
  const p = v.split(".").map(Number);
  return { major: p[0] || 0, minor: p[1] || 0, patch: p[2] || 0 };
}

function isVersionSupported(v: string): boolean {
  const { major, minor } = parseSemver(v);
  return major > 3 || (major === 3 && minor >= 11);
}

function getBundledPythonPath(): string | null {
  if (isDev) return null;
  const pf = process.platform === "win32" ? "win" : process.platform === "darwin" ? "darwin" : "linux";
  const exe = process.platform === "win32" ? "python.exe" : "bin/python3";
  const candidates = [
    path.join(process.resourcesPath, "python", exe),
    path.join(process.resourcesPath, "python", process.platform === "win32" ? "python.exe" : "python3"),
    path.join(process.resourcesPath, "python-runtime", pf, "python", exe),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) { console.log(`[backend] Bundled Python: ${p}`); return p; }
  }
  return null;
}

function findPythonCommand(): string | null {
  const b = getBundledPythonPath();
  if (b) return b;
  // Fall back to system Python if bundled python runtime is missing
  for (const cmd of ["python3", "python", "py"]) {
    const v = getPythonVersion(cmd);
    if (v && isVersionSupported(v)) { console.log(`[backend] System Python ${v}: ${cmd}`); return cmd; }
  }
  return null;
}

function getBundledBinaryPath(): string | null {
  if (isDev) return null;
  const isWin = process.platform === "win32";
  const candidates = [
    path.join(process.resourcesPath, "backend", isWin ? "watchdog_launcher.exe" : "watchdog_launcher"),
    path.join(process.resourcesPath, "backend", isWin ? "backend-server.exe" : "backend-server"),
    path.join(process.resourcesPath, isWin ? "watchdog_launcher.exe" : "watchdog_launcher"),
    path.join(process.resourcesPath, isWin ? "backend-server.exe" : "backend-server"),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) {
      console.log(`[backend] Bundled binary found: ${p}`);
      return p;
    }
  }
  console.warn(`[backend] Bundled binary NOT found. Checked:\n  ${candidates.join("\n  ")}\nRun 'node scripts/build-backend.js' before packaging.`);
  return null;
}

// CRITICAL: Build a clean, minimal env for the backend — do NOT spread
// ...process.env which may contain broken PATH, secrets, wrong Python refs.
function buildBackendEnv(extras: Record<string, string> = {}): NodeJS.ProcessEnv {
  const base: NodeJS.ProcessEnv = {
    PYTHONUNBUFFERED: "1",
    PYTHONDONTWRITEBYTECODE: "1",
    PYTHONIOENCODING: "utf-8",
    GIT_PYTHON_REFRESH: "quiet",
    LANG:         process.env.LANG         || "en_US.UTF-8",
    LC_ALL:       process.env.LC_ALL       || "en_US.UTF-8",
    TMPDIR:       process.env.TMPDIR       || process.env.TEMP  || process.env.TMP || "",
    TEMP:         process.env.TEMP         || process.env.TMPDIR || "",
    TMP:          process.env.TMP          || process.env.TMPDIR || "",
    SYSTEMROOT:   process.env.SYSTEMROOT   || "",
    SYSTEMDRIVE:  process.env.SYSTEMDRIVE  || "",
    WINDIR:       process.env.WINDIR       || "",
    APPDATA:      process.env.APPDATA      || "",
    LOCALAPPDATA: process.env.LOCALAPPDATA || "",
    PROGRAMDATA:  process.env.PROGRAMDATA  || "",
    HOME:         process.env.HOME         || process.env.USERPROFILE || "",
    USERPROFILE:  process.env.USERPROFILE  || process.env.HOME        || "",
    USERNAME:     process.env.USERNAME     || process.env.USER        || "",
    USER:         process.env.USER         || process.env.USERNAME    || "",
  };
  const pathParts: string[] = [];
  if (!isDev) {
    const pf = process.platform === "win32" ? "win" : process.platform === "darwin" ? "darwin" : "linux";

    // 1. Bundled Python on PATH
    const pyCandidates = [
      path.join(process.resourcesPath, "python"),
      path.join(process.resourcesPath, "python-runtime", pf, "python"),
    ];
    for (const pyDir of pyCandidates) {
      if (fs.existsSync(pyDir)) {
        pathParts.push(pyDir);
        const binDir = path.join(pyDir, process.platform === "win32" ? "Scripts" : "bin");
        if (fs.existsSync(binDir)) pathParts.push(binDir);
        break;
      }
    }

    // 2. Bundled Node on PATH
    const nodeCandidates = [
      path.join(process.resourcesPath, "node"),
      path.join(process.resourcesPath, "node-runtime", pf, "node"),
    ];
    for (const nodeDir of nodeCandidates) {
      if (fs.existsSync(nodeDir)) {
        pathParts.push(nodeDir);
        const binDir = path.join(nodeDir, "bin");
        if (fs.existsSync(binDir)) pathParts.push(binDir);
        break;
      }
    }

    // 3. Bundled Git on PATH
    const gitCandidates = [
      path.join(process.resourcesPath, "git", "cmd"),
      path.join(process.resourcesPath, "git"),
      path.join(process.resourcesPath, "git-runtime", pf, "git", "cmd"),
    ];
    for (const gitDir of gitCandidates) {
      if (fs.existsSync(gitDir)) {
        pathParts.push(gitDir);
        break;
      }
    }

  }
  pathParts.push(process.env.PATH || "");
  base.PATH = pathParts.join(path.delimiter);

  // 4. Bundled Tiktoken Cache (wired in both dev and packaged modes)
  const tiktokenCandidates = [
    path.join(process.resourcesPath, "tiktoken"),
    path.join(process.resourcesPath, "backend", "tiktoken"),
    path.join(getAppPathSafe(), "resources", "tiktoken"),
    path.join(__dirname, "..", "..", "resources", "tiktoken"),
  ];
  for (const tkDir of tiktokenCandidates) {
    if (fs.existsSync(tkDir)) {
      base.TIKTOKEN_CACHE_DIR = tkDir;
      break;
    }
  }

  Object.assign(base, extras);
  for (const k of Object.keys(base)) { if (base[k] === "") delete base[k]; }
  return base;
}

const CRASH_LOG_DIR = path.join(os.homedir(), ".code_os");
const CRASH_LOG_PATH = path.join(CRASH_LOG_DIR, "backend_crash.log");

function appendCrashLog(msg: string): void {
  try {
    if (!fs.existsSync(CRASH_LOG_DIR)) {
      fs.mkdirSync(CRASH_LOG_DIR, { recursive: true });
    }
    const timestamp = new Date().toISOString();
    fs.appendFileSync(CRASH_LOG_PATH, `[${timestamp}] ${msg}\n`);
  } catch (err) {
    console.error("[backend] Failed to write crash log:", err);
  }
}

export class BackendProcess {
  private process: ChildProcessWithoutNullStreams | null = null;
  lastError: string | null = null;
  sessionToken: string | null = null;
  restartTimestamps: number[] = [];
  isStopping: boolean = false;
  circuitBreakerTripped: boolean = false;
  onCircuitBreakerTripped?: () => void;
  private _restartTimer: NodeJS.Timeout | null = null;
  private _tokenReady: Promise<string>;
  private _tokenResolve!: (token: string) => void;

  constructor() {
    this._tokenReady = new Promise<string>((resolve) => { this._tokenResolve = resolve; });
    this._checkPriorCrashLog();
  }

  private _checkPriorCrashLog(): void {
    try {
      if (fs.existsSync(CRASH_LOG_PATH)) {
        const content = fs.readFileSync(CRASH_LOG_PATH, "utf-8").trim();
        if (content) {
          const lines = content.split("\n");
          const recent = lines.slice(-5).join("\n  ");
          console.warn(`[backend] Prior crash log detected (${lines.length} lines):\n  ${recent}`);
        }
      }
    } catch {}
  }

  waitForToken(timeoutMs = 30_000): Promise<string> {
    return Promise.race([
      this._tokenReady,
      new Promise<string>((_, reject) =>
        setTimeout(() => reject(new Error("Timed out waiting for backend session token")), timeoutMs)
      ),
    ]);
  }

  private _readSessionTokenFromFile(tokenPath: string): string | null {
    try {
      if (!fs.existsSync(tokenPath)) return null;
      const raw = fs.readFileSync(tokenPath, "utf-8").trim();

      // Try parsing as JSON (new format)
      let token: string | null = null;
      try {
        const data = JSON.parse(raw);
        token = data.token;
        const expiresAt = data.expires_at;

        // Check expiry
        if (expiresAt && Date.now() / 1000 >= expiresAt) {
          console.log("[backend] Session token expired, deleting");
          try { fs.unlinkSync(tokenPath); } catch {}
          token = null;
        }
      } catch (jsonError) {
        // Legacy plain-text format (v3.0.0) - treat as expired
        console.log("[backend] Legacy token format detected, treating as expired");
        try { fs.unlinkSync(tokenPath); } catch {}
        token = null;
      }

      if (token && token.length === 64) {
        this.sessionToken = token;
        console.log("[backend] Session token loaded from file");
        return token;
      }
      return null;
    } catch (err) {
      console.warn("[backend] Could not read session token:", err);
      return null;
    }
  }

  async start(): Promise<void> {
    if (this.process) return;
    this.lastError = null;
    const findToken = (): string | null => {
      const candidates = [
        path.join(getUserDataPath(), "session_token"),
        path.join(process.env.APPDATA || "", "code_os", "session_token"),
        path.join(os.homedir(), ".code-os", "session_token"),
        path.join(os.homedir(), ".code_os", "session_token"),
      ];
      for (const p of candidates) {
        const t = this._readSessionTokenFromFile(p);
        if (t) return t;
      }
      return null;
    };

    if (isDev) {
      console.log("[backend] Dev mode: attaching to dev backend on 127.0.0.1:8000");
      for (let i = 0; i < 30; i++) {
        const token = findToken();
        if (token) {
          this._tokenResolve(token);
          return;
        }
        await new Promise((r) => setTimeout(r, 500));
      }
      return;
    }

    if (await this.isBackendHealthy()) {
      const token = findToken();
      if (token && (await this.verifyTokenWithBackend(token))) {
        console.log("[backend] Reusing existing healthy backend on 127.0.0.1:8000 with valid session token");
        this.sessionToken = token;
        this._tokenResolve(token);
        return;
      }
      console.warn("[backend] Existing process on port 8000 is unhealthy or token rejected; terminating stale process");
      killPort(8000);
      await new Promise((r) => setTimeout(r, 400));
    } else {
      // Ensure port 8000 is completely free of any zombie or hung processes
      killPort(8000);
      await new Promise((r) => setTimeout(r, 200));
    }

    const backendDir = path.join(process.resourcesPath, "backend");
    const bundledPython = getBundledPythonPath();
    const watchdogPy = path.join(backendDir, "watchdog_launcher.py");
    const bin = getBundledBinaryPath();

    // Strategy 1: Bundled Python Runtime (Primary & Recommended)
    // Instantly boots Python 3.11 with pre-installed FastAPI, Uvicorn, and dependencies.
    // Sub-second startup, immune to PyInstaller frozen extraction issues.
    if (bundledPython && fs.existsSync(backendDir)) {
      console.log(`[backend] Starting backend with bundled Python: ${bundledPython}`);
      const args = fs.existsSync(watchdogPy)
        ? [watchdogPy, "--worker"]
        : ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"];

      await this._spawnProcess(bundledPython, args, {
        cwd: backendDir,
        env: buildBackendEnv({
          CODE_OS_DATA_DIR: getUserDataPath(),
          CODE_OS_HOME: getUserDataPath(),
          PYTHONPATH: backendDir,
        }),
      });
      return;
    }

    // Strategy 2: Bundled PyInstaller binary (Fallback if bundled Python runtime is not present)
    if (bin) {
      console.log("[backend] Starting bundled binary (first launch may take 15-20 s)...");
      await this._spawnProcess(bin, [], {
        cwd: path.dirname(bin),
        env: buildBackendEnv({
          CODE_OS_DATA_DIR: getUserDataPath(),
          CODE_OS_HOME: getUserDataPath(),
        }),
      });
      return;
    }

    // Strategy 3: System Python fallback (Dev or machines with system Python 3.11+)
    const systemPython = findPythonCommand();
    if (systemPython && fs.existsSync(backendDir)) {
      console.log(`[backend] Starting backend with system Python: ${systemPython}`);
      const args = fs.existsSync(watchdogPy)
        ? [watchdogPy, "--worker"]
        : ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"];

      await this._spawnProcess(systemPython, args, {
        cwd: backendDir,
        env: buildBackendEnv({
          CODE_OS_DATA_DIR: getUserDataPath(),
          CODE_OS_HOME: getUserDataPath(),
          PYTHONPATH: backendDir,
        }),
      });
      return;
    }

    // Strategy 4: All spawn strategies failed — show user-friendly guidance
    this.lastError =
      "The CODE OS backend could not start because Python 3.11+ is not available on this installation.\n\n" +
      "Please download the latest release installer from:\n" +
      "  https://github.com/Roopesh-kosuri/code-os/releases\n\n" +
      "Or install Python 3.11+ from https://python.org/downloads and relaunch CODE OS.";
    console.error(`[backend] ${this.lastError}`);
    try {
      dialog.showErrorBox(
        "CODE OS - Backend Not Available",
        "The Python backend runtime failed to start.\n\n" +
        "Please download the latest release installer from:\n  https://github.com/Roopesh-kosuri/code-os/releases\n\n" +
        "Or install Python 3.11+ from python.org/downloads and relaunch CODE OS.",
      );
    } catch { /* headless */ }
  }

  private async _spawnProcess(cmd: string, args: string[], options: { cwd: string; env: NodeJS.ProcessEnv }): Promise<void> {
    const spawnOpts = buildSpawnOptions(process.platform, options.env, options.cwd);
    try {
      this.process = spawn(cmd, args, spawnOpts as any) as ChildProcessWithoutNullStreams;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      this.lastError = `Failed to spawn backend process: ${msg}`;
      console.error(`[backend] ${this.lastError}`);
      return;
    }

    this.process.on("error", (err) => { this.lastError = `Backend process error: ${err.message}`; console.error(`[backend] ${this.lastError}`); });

    this.process.stdout.on("data", (data: Buffer) => {
      for (const line of data.toString().split("\n")) {
        const t = line.trim();
        if (t.startsWith("CODE_OS_SESSION_TOKEN=")) {
          const token = t.slice("CODE_OS_SESSION_TOKEN=".length).trim();
          if (token) { this.sessionToken = token; this._tokenResolve(token); console.log("[backend] session token captured"); }
        } else if (t) { console.log(`[backend] ${t}`); }
      }
    });

    this.process.stderr.on("data", (data: Buffer) => {
      const msg = data.toString().trim();
      if (msg) {
        console.error(`[backend] ${msg}`);
        appendCrashLog(`[STDERR] ${msg}`);
      }
      if (msg.includes("Error:") || msg.includes("Traceback") || msg.includes("ModuleNotFoundError")) this.lastError = msg;
    });

    this.process.on("exit", (code, signal) => {
      console.log(`[backend] exited with code ${code}, signal ${signal}`);
      this.process = null;

      if (this.isStopping) {
        console.log("[backend] Intentional shutdown complete");
        return;
      }

      const exitReason = `Backend process exited unexpectedly (code: ${code}, signal: ${signal})`;
      this.lastError = exitReason;
      appendCrashLog(`[CRASH] ${exitReason}`);

      const now = Date.now();
      this.restartTimestamps = this.restartTimestamps.filter((t) => now - t <= 60_000);

      if (this.restartTimestamps.length >= 3) {
        this.circuitBreakerTripped = true;
        const alertMsg = "Backend crashed 3 times, please restart app.";
        this.lastError = alertMsg;
        appendCrashLog(`[CIRCUIT BREAKER] ${alertMsg}`);
        console.error(`[backend] ${alertMsg}`);
        try {
          dialog.showErrorBox("Backend crashed repeatedly — see crash log", alertMsg);
        } catch {}
        if (this.onCircuitBreakerTripped) {
          this.onCircuitBreakerTripped();
        }
        return;
      }

      this.restartTimestamps.push(now);
      // S1: 1s, 2s, 4s exponential backoff on unexpected exit
      const attempt = this.restartTimestamps.length;
      const backoffMs = Math.min(4000, 1000 * Math.pow(2, attempt - 1));
      console.log(`[backend] Auto-restarting in ${backoffMs}ms (restart attempt ${attempt}/3 in 60s window)...`);
      this._restartTimer = setTimeout(() => {
        this._restartTimer = null;
        if (!this.isStopping && !this.circuitBreakerTripped) {
          void this.start().catch((err) => {
            console.error("[backend] Auto-restart failed:", err);
          });
        }
      }, backoffMs);
    });
  }

  async isBackendHealthy(): Promise<boolean> {
    try { return (await fetch("http://127.0.0.1:8000/health", { signal: AbortSignal.timeout(800) })).ok; }
    catch { return false; }
  }

  async verifyTokenWithBackend(token: string): Promise<boolean> {
    try {
      const res = await fetch("http://127.0.0.1:8000/api/workspaces", {
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(1000),
      });
      return res.ok;
    } catch {
      return false;
    }
  }

  stop(): void {
    this.isStopping = true;
    if (this._restartTimer) {
      clearTimeout(this._restartTimer);
      this._restartTimer = null;
    }
    if (this.process) {
      const proc = this.process;
      this.process = null;
      try {
        if (proc.pid && process.platform === "win32") {
          try {
            execSync(`taskkill /F /T /PID ${proc.pid}`, { stdio: "ignore" });
          } catch {}
        }
        proc.kill("SIGTERM");
        setTimeout(() => {
          try {
            if (proc && !proc.killed) {
              proc.kill("SIGKILL");
            }
          } catch {}
        }, 3000);
      } catch {
        proc.kill();
      }
    }
    killPort(8000);
  }

  async restart(): Promise<void> {
    if (isDev) {
      console.log("[backend] Dev mode: IPC restart received; dev backend is managed by runner");
      return;
    }
    console.log("[backend] Manual restart initiated via supervision IPC");
    this.stop();
    // Keep isStopping true during shutdown delay to prevent exit handler race condition
    await new Promise((r) => setTimeout(r, 1000));
    this.isStopping = false;
    this.circuitBreakerTripped = false;
    this._tokenReady = new Promise<string>((resolve) => { this._tokenResolve = resolve; });
    this.sessionToken = null;
    await this.start();
  }
}