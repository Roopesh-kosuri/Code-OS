import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import path from "node:path";
import { app } from "electron";
import isDev from "electron-is-dev";

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

    this.process = spawn("python", args, {
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
