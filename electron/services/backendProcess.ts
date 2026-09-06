import { ChildProcessWithoutNullStreams, spawn, execSync } from "node:child_process";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import { app, dialog } from "electron";

const isDev = !app.isPackaged;

function getPythonVersion(cmd: string): string | null {
  try {
    const output = execSync(`${cmd} --version`, { stdio: "pipe" }).toString().trim();
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
  const p = path.join(process.resourcesPath, "python-runtime", pf, "python", exe);
  if (fs.existsSync(p)) { console.log(`[backend] Bundled Python: ${p}`); return p; }
  return null;
}

function findPythonCommand(): string | null {
  const b = getBundledPythonPath();
  if (b) return b;
  for (const cmd of ["python3", "python"]) {
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
    const pyDir   = path.join(process.resourcesPath, "python-runtime", pf, "python");
    const nodeDir = path.join(process.resourcesPath, "node-runtime",   pf, "node");
    if (fs.existsSync(pyDir))   { pathParts.push(pyDir);   if (process.platform !== "win32") pathParts.push(path.join(pyDir,   "bin")); }
    if (fs.existsSync(nodeDir)) { pathParts.push(nodeDir); if (process.platform !== "win32") pathParts.push(path.join(nodeDir, "bin")); }
  }
  pathParts.push(process.env.PATH || "");
  base.PATH = pathParts.join(path.delimiter);
  Object.assign(base, extras);
  for (const k of Object.keys(base)) { if (base[k] === "") delete base[k]; }
  return base;
}

export class BackendProcess {
  private process: ChildProcessWithoutNullStreams | null = null;
  lastError: string | null = null;
  sessionToken: string | null = null;
  private _tokenReady: Promise<string>;
  private _tokenResolve!: (token: string) => void;

  constructor() {
    this._tokenReady = new Promise<string>((resolve) => { this._tokenResolve = resolve; });
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
        path.join(app.getPath("userData"), "session_token"),
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
      console.log("[backend] Reusing existing backend on 127.0.0.1:8000");
      const token = findToken();
      if (token) {
        this._tokenResolve(token);
        return;
      }
    }

    // Strategy 1: Bundled PyInstaller binary (correct packaged build)
    const bin = getBundledBinaryPath();
    if (bin) {
      console.log("[backend] Starting bundled binary (first launch may take 15-20 s)...");
      await this._spawnProcess(bin, [], {
        cwd: path.dirname(bin),
        env: buildBackendEnv({
          CODE_OS_DATA_DIR: app.getPath("userData"),
          CODE_OS_HOME: app.getPath("userData"),
        }),
      });
      return;
    }

    // Strategy 2: System Python + uvicorn (incomplete package / dev without binary)
    const backendDir = path.join(process.resourcesPath, "backend");
    const uvicornArgs = ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"];
    const pythonCmd = findPythonCommand();

    if (!pythonCmd) {
      this.lastError =
        "The CODE OS backend binary is missing from this installation and " +
        "Python 3.11+ is not installed on this machine.\n\n" +
        "Please download the latest release from:\n" +
        "  https://github.com/Roopesh-kosuri/code-os/releases\n\n" +
        "Developers: run 'npm run build:backend-exe' before packaging.";
      console.error(`[backend] ${this.lastError}`);
      try {
        dialog.showErrorBox(
          "CODE OS - Backend Not Available",
          "The bundled backend binary is missing from this installation.\n\n" +
          "Download the latest installer from:\n  https://github.com/Roopesh-kosuri/code-os/releases\n\n" +
          "Developers: run 'npm run build:backend-exe' before packaging.",
        );
      } catch { /* headless */ }
      return;
    }

    await this._spawnProcess(pythonCmd, uvicornArgs, {
      cwd: backendDir,
      env: buildBackendEnv({ CODE_OS_HOME: app.getPath("userData"), PYTHONPATH: backendDir }),
    });
  }

  private async _spawnProcess(cmd: string, args: string[], options: { cwd: string; env: NodeJS.ProcessEnv }): Promise<void> {
    try {
      this.process = spawn(cmd, args, options) as ChildProcessWithoutNullStreams;
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
      if (msg) console.error(`[backend] ${msg}`);
      if (msg.includes("Error:") || msg.includes("Traceback") || msg.includes("ModuleNotFoundError")) this.lastError = msg;
    });

    this.process.on("exit", (code) => {
      console.log(`[backend] exited with code ${code}`);
      if (code !== 0 && code !== null) this.lastError = `Backend process exited unexpectedly with code ${code}`;
      this.process = null;
    });
  }

  private async isBackendHealthy(): Promise<boolean> {
    try { return (await fetch("http://127.0.0.1:8000/health", { signal: AbortSignal.timeout(800) })).ok; }
    catch { return false; }
  }

  stop(): void {
    if (!this.process) return;
    this.process.kill();
    this.process = null;
  }
}