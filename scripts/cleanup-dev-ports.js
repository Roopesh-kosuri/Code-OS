import { execSync } from "node:child_process";

export function cleanupDevPorts() {
  const ports = [8000, 5176, 5177, 5178, 5179];

  if (process.platform === "win32") {
    // 1. Kill any stray electron processes
    try {
      execSync("taskkill /F /IM electron.exe", { stdio: "ignore" });
    } catch {}

    // 2. Kill any processes holding ports 8000, 5176-5179
    try {
      const netstatOutput = execSync("netstat -ano -p tcp", { stdio: "pipe" }).toString();
      const pidsToKill = new Set();
      for (const line of netstatOutput.split(/\r?\n/)) {
        if (!line.includes("LISTENING")) continue;
        for (const port of ports) {
          if (line.includes(`:${port} `) || line.includes(`:${port}\t`)) {
            const parts = line.trim().split(/\s+/);
            const pid = parts[parts.length - 1];
            if (pid && pid !== "0" && pid !== String(process.pid)) {
              pidsToKill.add(pid);
            }
          }
        }
      }
      for (const pid of pidsToKill) {
        try {
          execSync(`taskkill /F /T /PID ${pid}`, { stdio: "ignore" });
        } catch {}
      }
    } catch {}
  } else {
    for (const port of ports) {
      try {
        const pids = execSync(`lsof -ti :${port}`, { stdio: "pipe" }).toString().trim();
        if (pids) {
          execSync(`kill -9 ${pids.split(/\s+/).join(" ")}`, { stdio: "ignore" });
        }
      } catch {}
    }
  }
}

if (process.argv[1] && process.argv[1].endsWith("cleanup-dev-ports.js")) {
  cleanupDevPorts();
}
