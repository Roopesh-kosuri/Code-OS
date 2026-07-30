import { ChildProcessWithoutNullStreams, spawn, execSync } from "node:child_process";
import path from "node:path";
import { app, dialog } from "electron";

const isDev = !app.isPackaged;

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

function findPythonCommand(): string {
  const candidates = ["python3", "python"];
  for (const cmd of candidates) {
    const version = getPythonVersion(cmd);
    if (version && isVersionSupported(version)) {
      console.log(`[backend] Found supported Python version ${version} via command: ${cmd}`);
      return cmd;
    }
  }

  const errorMsg = "Error: A compatible Python interpreter (>= 3.11) was not found in PATH.\n" +
    "Please install Python 3.11 or newer and add it to your environment variables.";
  console.error(`[backend] ${errorMsg}`);

  try {
    dialog.showErrorBox("Python Required", errorMsg);
  } catch {
    // ignore dialog failures (e.g. if run before ready)
  }
  throw new Error("Python >= 3.11 not found");
}

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
  waitForToken(timeoutMs = 15_000): Promise<string> {
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

    if (await this.isBackendHealthy()) {
      console.log("[backend] reusing existing backend on 127.0.0.1:8000");
      try {
        const fs = await import("node:fs");
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

    const projectRoot = isDev ? process.cwd() : process.resourcesPath;
    const args = ["-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"];

    if (isDev) {
      args.push("--reload");
    }

    let pythonCmd: string;
    try {
      pythonCmd = findPythonCommand();
    } catch (err: any) {
      this.lastError = err?.message || "Python >= 3.11 not found in system PATH";
      console.error(`[backend] ${this.lastError}`);
      return;
    }

    try {
      this.process = spawn(pythonCmd, args, {
        cwd: projectRoot,
        env: {
          ...process.env,
          CODE_OS_HOME: app.getPath("userData"),
          PYTHONPATH: projectRoot
        }
      });
    } catch (err: any) {
      this.lastError = `Failed to spawn Python process: ${err?.message || err}`;
      console.error(`[backend] ${this.lastError}`);
      return;
    }

    this.process.on("error", (err) => {
      this.lastError = `Python process error: ${err.message}`;
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
