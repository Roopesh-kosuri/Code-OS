import { ChildProcessWithoutNullStreams, spawn, execSync } from "node:child_process";
import path from "node:path";
import fs from "node:fs";
import { app, dialog } from "electron";

const isDev = !app.isPackaged;

// ── Python version detection (fallback path only) ─────────────────────────────

function getPythonVersion(cmd: string): string | null {
  try {
    const output = execSync(`${cmd} --version`, { stdio: "pipe" }).toString().trim();
    const match = output.match(/Python\s+([0-9\.]+)/i);
    if (match && match[1]) {
      return match[1];
    }
  } catch {
    // ignore
  }
  return null;
}

function parseSemver(versionStr: string) {
  const parts = versionStr.split(".").map(Number);
  return {
    major: parts[0] || 0,
    minor: parts[1] || 0,
    patch: parts[2] || 0
  };
}

function isVersionSupported(versionStr: string): boolean {
  const ver = parseSemver(versionStr);
  if (ver.major > 3) return true;
  if (ver.major === 3 && ver.minor >= 11) return true;
  return false;
}

function getBundledPythonPath(): string | null {
  if (isDev) return null;
  const platformFolder = process.platform === "win32" ? "win" : process.platform;
  const exeName = process.platform === "win32" ? "python.exe" : "bin/python3";
  const candidatePath = path.join(process.resourcesPath, "python-runtime", platformFolder, "python", exeName);
  if (fs.existsSync(candidatePath)) {
    console.log(`[backend] Found bundled standalone Python runtime at: ${candidatePath}`);
    return candidatePath;
  }
  return null;
}

function findPythonCommand(): string | null {
  const bundled = getBundledPythonPath();
  if (bundled) {
    return bundled;
  }

  const candidates = ["python3", "python"];
  for (const cmd of candidates) {
    const version = getPythonVersion(cmd);
    if (version && isVersionSupported(version)) {
      console.log(`[backend] Found supported Python version ${version} via command: ${cmd}`);
      return cmd;
    }
  }
  return null;
}

// ── Bundled binary path resolution ────────────────────────────────────────────

function getBundledBinaryPath(): string | null {
  if (isDev) return null; // dev always uses system Python

  const exeName = process.platform === "win32" ? "backend-server.exe" : "backend-server";
  const candidatePath = path.join(process.resourcesPath, exeName);

  if (fs.existsSync(candidatePath)) {
    console.log(`[backend] Found bundled binary at: ${candidatePath}`);
    return candidatePath;
  }

  console.warn(`[backend] Bundled binary NOT found at: ${candidatePath}`);
  return null;
}

// ── BackendProcess class ──────────────────────────────────────────────────────

export class BackendProcess {
  private process: ChildProcessWithoutNullStreams | null = null;
  lastError: string | null = null;

  /**
   * The session token emitted by the backend on startup.
   * The backend prints a line:  CODE_OS_SESSION_TOKEN=<hex>
   * We capture it here so Electron can inject it into API requests.
   */
  sessionToken: string | null = null;

  /** Promise that resolves once the session token has been captured. */
  private _tokenReady: Promise<string>;
  private _tokenResolve!: (token: string) => void;

  constructor() {
    this._tokenReady = new Promise<string>((resolve) => {
      this._tokenResolve = resolve;
    });
  }

  /** Wait until the backend has emitted its session token. */
  waitForToken(timeoutMs = 30_000): Promise<string> {
    return Promise.race([
      this._tokenReady,
      new Promise<string>((_, reject) =>
        setTimeout(() => reject(new Error("Timed out waiting for backend session token")), timeoutMs)
      )
    ]);
  }

  async start(): Promise<void> {
    if (this.process) {
      return;
    }

    this.lastError = null;

    if (isDev) {
      // In dev mode, dev:backend is launched by concurrently (scripts/dev-backend.js).
      // Electron attaches to it and reads the session token without spawning a duplicate uvicorn.
      console.log("[backend] Dev mode active: attaching to dev backend on 127.0.0.1:8000");
      for (let i = 0; i < 30; i++) {
        try {
          const os = await import("node:os");
          const path_ = await import("node:path");
          const tokenPath = path_.join(os.homedir(), ".code-os", "session_token");
          if (fs.existsSync(tokenPath)) {
            const token = fs.readFileSync(tokenPath, "utf-8").trim();
            if (token.length === 64) {
              this.sessionToken = token;
              this._tokenResolve(token);
              console.log("[backend] session token loaded from file");
              return;
            }
          }
        } catch {
          // retry
        }
        await new Promise((r) => setTimeout(r, 500));
      }
      return;
    }

    if (await this.isBackendHealthy()) {
      console.log("[backend] reusing existing backend on 127.0.0.1:8000");
      try {
        const os = await import("node:os");
        const path_ = await import("node:path");
        const tokenPath = path_.join(os.homedir(), ".code-os", "session_token");
        const token = fs.readFileSync(tokenPath, "utf-8").trim();
        this.sessionToken = token;
        this._tokenResolve(token);
        console.log("[backend] session token loaded from file");
      } catch (err) {
        console.warn("[backend] could not read session token from file:", err);
      }
      return;
    }

    // ── Strategy 1: Bundled PyInstaller binary (packaged builds) ──────────────
    const bundledBinary = getBundledBinaryPath();
    if (bundledBinary) {
      console.log("[backend] Starting bundled backend binary (first start may take ~15-20s for extraction)...");
      await this._spawnProcess(bundledBinary, [], {
        cwd: path.dirname(bundledBinary),
        env: {
          ...process.env,
          CODE_OS_HOME: app.getPath("userData"),
          PYTHONUNBUFFERED: "1",
        }
      });
      return;
    }

    // ── Strategy 2: System Python + uvicorn (dev mode, or bundled binary missing) ──
    const backendDir = isDev ? path.join(process.cwd(), "backend") : path.join(process.resourcesPath, "backend");
    const moduleTarget = "app.main:app";
    const uvicornArgs = ["-m", "uvicorn", moduleTarget, "--host", "127.0.0.1", "--port", "8000"];

    if (isDev) {
      uvicornArgs.push("--reload");
    }

    const pythonCmd = findPythonCommand();

    if (!pythonCmd) {
      this.lastError =
        "Python 3.11+ was not found on this system. " +
        "Please install it from python.org/downloads and relaunch CODE OS. " +
        "(On Windows, check 'Add Python to PATH' during setup.)";
      console.error(`[backend] ${this.lastError}`);

      try {
        dialog.showErrorBox(
          "Python Required — CODE OS",
          "Python 3.11 or newer is required to run the CODE OS backend.\n\n" +
          "Please install it from:\n  https://python.org/downloads\n\n" +
          "On Windows: check 'Add Python to PATH' during installation.\n" +
          "Then relaunch CODE OS."
        );
      } catch {
        // ignore dialog failures
      }
      return;
    }

    await this._spawnProcess(pythonCmd, uvicornArgs, {
      cwd: backendDir,
      env: {
        ...process.env,
        CODE_OS_HOME: app.getPath("userData"),
          PYTHONUNBUFFERED: "1",
        PYTHONPATH: backendDir
      }
    });
  }

  private async _spawnProcess(
    cmd: string,
    args: string[],
    options: { cwd: string; env: NodeJS.ProcessEnv }
  ): Promise<void> {
    try {
      this.process = spawn(cmd, args, options) as ChildProcessWithoutNullStreams;
    } catch (err: any) {
      this.lastError = `Failed to spawn backend process: ${err?.message || err}`;
      console.error(`[backend] ${this.lastError}`);
      return;
    }

    this.process.on("error", (err) => {
      this.lastError = `Backend process error: ${err.message}`;
      console.error(`[backend] ${this.lastError}`);
    });

    this.process.stdout.on("data", (data: Buffer) => {
      const text = data.toString();
      for (const line of text.split("\n")) {
        const trimmed = line.trim();
        if (trimmed.startsWith("CODE_OS_SESSION_TOKEN=")) {
          const token = trimmed.slice("CODE_OS_SESSION_TOKEN=".length).trim();
          if (token) {
            this.sessionToken = token;
            this._tokenResolve(token);
            console.log("[backend] session token captured from stdout");
          }
        } else {
          console.log(`[backend] ${trimmed}`);
        }
      }
    });

    this.process.stderr.on("data", (data) => {
      const msg = data.toString().trim();
      console.error(`[backend] ${msg}`);
      if (msg.includes("Error:") || msg.includes("Traceback") || msg.includes("ModuleNotFoundError")) {
        this.lastError = msg;
      }
    });

    this.process.on("exit", (code) => {
      console.log(`[backend] exited with code ${code}`);
      if (code !== 0 && code !== null) {
        this.lastError = `Python backend exited unexpectedly with code ${code}`;
      }
      this.process = null;
    });
  }

  private async isBackendHealthy(): Promise<boolean> {
    try {
      const response = await fetch("http://127.0.0.1:8000/health", { signal: AbortSignal.timeout(800) });
      return response.ok;
    } catch {
      return false;
    }
  }

  stop(): void {
    if (!this.process) {
      return;
    }

    this.process.kill();
    this.process = null;
  }
}
