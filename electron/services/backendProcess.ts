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

  async start(): Promise<void> {
    if (this.process) {
      return;
    }

    if (await this.isBackendHealthy()) {
      console.log("[backend] reusing existing backend on 127.0.0.1:8000");
      return;
    }

    const projectRoot = isDev ? process.cwd() : path.dirname(app.getPath("exe"));
    const args = ["-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"];

    if (isDev) {
      args.push("--reload");
    }

    let pythonCmd: string;
    try {
      pythonCmd = findPythonCommand();
    } catch (err) {
      return;
    }

    this.process = spawn(pythonCmd, args, {
      cwd: projectRoot,
      env: {
        ...process.env,
        CODE_OS_HOME: app.getPath("userData")
      }
    });

    this.process.stdout.on("data", (data) => {
      console.log(`[backend] ${data.toString().trim()}`);
    });

    this.process.stderr.on("data", (data) => {
      console.error(`[backend] ${data.toString().trim()}`);
    });

    this.process.on("exit", (code) => {
      console.log(`[backend] exited with code ${code}`);
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
