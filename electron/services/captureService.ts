import http from "node:http";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import crypto from "node:crypto";
import { BrowserWindow, app } from "electron";

export interface CaptureRequest {
  mode?: "preview" | "app_window";
  target?: string;
  workspace?: string;
  width?: number;
  height?: number;
}

export interface CaptureResponse {
  success: boolean;
  image_base64?: string;
  format?: string;
  width?: number;
  height?: number;
  error?: string;
}

export function isPrivateOrMetadataHost(hostname: string): boolean {
  const host = hostname.toLowerCase().trim();
  if (host === "localhost" || host === "127.0.0.1" || host === "::1" || host === "0.0.0.0") {
    return true;
  }
  if (host === "169.254.169.254" || host === "fd00:ec2::254" || host === "100.100.100.200") {
    return true;
  }
  const parts = host.split(".");
  if (parts.length === 4) {
    const nums = parts.map((p) => parseInt(p, 10));
    if (nums.every((n) => !isNaN(n) && n >= 0 && n <= 255)) {
      const [b0, b1] = nums;
      if (b0 === 127 || b0 === 10 || b0 === 0) return true;
      if (b0 === 172 && b1 >= 16 && b1 <= 31) return true;
      if (b0 === 192 && b1 === 168) return true;
      if (b0 === 169 && b1 === 254) return true;
      if (b0 === 100 && b1 >= 64 && b1 <= 127) return true;
    }
  }
  if (host.startsWith("fc") || host.startsWith("fd") || host.startsWith("fe80")) {
    return true;
  }
  return false;
}

export class OffscreenWindowPool {
  private windows: BrowserWindow[] = [];
  private maxSize: number = 3;

  async acquire(width: number = 1280, height: number = 900): Promise<BrowserWindow> {
    // Filter out destroyed windows
    this.windows = this.windows.filter((w) => !w.isDestroyed());

    // Reuse existing idle window if available
    const idle = this.windows.find((w) => !w.webContents.isLoading());
    if (idle) {
      try {
        idle.setSize(width, height);
        await idle.webContents.session.clearCache();
      } catch {
        // Ignore cache errors on reused session
      }
      return idle;
    }

    // Create new window if pool not full
    if (this.windows.length < this.maxSize) {
      const win = new BrowserWindow({
        show: false,
        width,
        height,
        frame: false,
        webPreferences: {
          offscreen: true,
          javascript: true,
          webSecurity: true,
          allowRunningInsecureContent: false,
          contextIsolation: true,
        },
      });
      this.windows.push(win);
      return win;
    }

    // Pool full, wait for one to become available (up to 15s timeout)
    return new Promise<BrowserWindow>((resolve, reject) => {
      const startTime = Date.now();
      const interval = setInterval(async () => {
        this.windows = this.windows.filter((w) => !w.isDestroyed());
        const available = this.windows.find((w) => !w.webContents.isLoading());
        if (available) {
          clearInterval(interval);
          try {
            available.setSize(width, height);
            await available.webContents.session.clearCache();
          } catch {
            // Ignore
          }
          resolve(available);
          return;
        }
        if (Date.now() - startTime > 15000) {
          clearInterval(interval);
          reject(new Error("Window pool exhausted: timeout waiting for idle offscreen window"));
        }
      }, 100);
    });
  }

  release(win: BrowserWindow | null): void {
    if (win && !win.isDestroyed()) {
      try {
        win.webContents.stop();
        win.webContents.session.clearCache().catch(() => {});
      } catch {
        // Ignore errors during release
      }
    }
  }

  destroyAll(): void {
    for (const win of this.windows) {
      try {
        if (!win.isDestroyed()) {
          win.destroy();
        }
      } catch {
        // Ignore
      }
    }
    this.windows = [];
  }
}

export class CaptureService {
  private server: http.Server | null = null;
  private port: number = 5178;
  private getMainWindow: () => BrowserWindow | null;
  private pool: OffscreenWindowPool = new OffscreenWindowPool();
  public sessionToken: string | null = null;

  constructor(getMainWindow: () => BrowserWindow | null, port: number = 5178, token: string | null = null) {
    this.getMainWindow = getMainWindow;
    this.port = port;
    this.sessionToken = token;
  }

  public resolveSessionToken(): string | null {
    if (this.sessionToken) return this.sessionToken;
    if (process.env.CODE_OS_SESSION_TOKEN) {
      return process.env.CODE_OS_SESSION_TOKEN.trim();
    }
    const searchPaths: string[] = [];
    try {
      if (typeof app !== "undefined" && app?.getPath) {
        searchPaths.push(path.join(app.getPath("userData"), "session_token"));
      }
    } catch {}

    searchPaths.push(
      path.join(os.homedir(), ".code-os", "session_token"),
      path.join(os.homedir(), ".code_os", "session_token"),
      path.join(process.env.APPDATA || "", "code_os", "session_token")
    );

    for (const p of searchPaths) {
      try {
        if (p && fs.existsSync(p)) {
          const raw = fs.readFileSync(p, "utf-8").trim();
          try {
            const data = JSON.parse(raw);
            if (data?.token && typeof data.token === "string") return data.token;
          } catch {
            if (raw.length === 64) return raw;
          }
        }
      } catch {}
    }
    return null;
  }

  public validateToken(provided: string, expected: string): boolean {
    if (!provided || !expected) return false;
    const bufA = Buffer.from(provided, "utf-8");
    const bufB = Buffer.from(expected, "utf-8");
    if (bufA.length !== bufB.length) return false;
    return crypto.timingSafeEqual(bufA, bufB);
  }

  public start(): Promise<number> {
    return new Promise((resolve, reject) => {
      this.server = http.createServer(async (req, res) => {
        // Restrict CORS: only allow renderer origin http://127.0.0.1:5176 or http://localhost:5176
        const origin = req.headers["origin"] || "";
        const ALLOWED_ORIGINS = ["http://127.0.0.1:5176", "http://localhost:5176"];
        if (typeof origin === "string" && ALLOWED_ORIGINS.includes(origin)) {
          res.setHeader("Access-Control-Allow-Origin", origin);
        }
        res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS, GET");
        res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization, x-session-token");

        if (req.method === "OPTIONS") {
          res.writeHead(200);
          res.end();
          return;
        }

        if (req.method === "GET" && req.url === "/health") {
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ status: "ok", service: "code-os-capture" }));
          return;
        }

        if (req.method === "POST" && req.url === "/capture") {
          // Authentication check
          const authHeader = req.headers["authorization"] || "";
          const tokenHeader = req.headers["x-session-token"] || "";
          let token = "";
          if (typeof authHeader === "string" && authHeader.toLowerCase().startsWith("bearer ")) {
            token = authHeader.slice(7).trim();
          } else if (typeof tokenHeader === "string") {
            token = tokenHeader.trim();
          }

          const expectedToken = this.resolveSessionToken();
          if (!expectedToken || !this.validateToken(token, expectedToken)) {
            res.writeHead(401, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ success: false, error: "Unauthorized: Missing or invalid session token" }));
            return;
          }

          let body = "";
          req.on("data", (chunk) => {
            body += chunk;
          });
          req.on("end", async () => {
            try {
              const data: CaptureRequest = JSON.parse(body || "{}");
              const result = await this.handleCapture(data);
              res.writeHead(result.success ? 200 : 400, { "Content-Type": "application/json" });
              res.end(JSON.stringify(result));
            } catch (err: any) {
              res.writeHead(500, { "Content-Type": "application/json" });
              res.end(JSON.stringify({ success: false, error: err?.message || String(err) }));
            }
          });
          return;
        }

        res.writeHead(404, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ success: false, error: "Not found" }));
      });

      this.server.listen(this.port, "127.0.0.1", () => {
        console.log(`[capture] Hardened Capture service running on http://127.0.0.1:${this.port}`);
        resolve(this.port);
      });

      this.server.on("error", (err: any) => {
        if (err.code === "EADDRINUSE") {
          console.warn(`[capture] Port ${this.port} in use, attempting fallback port...`);
          this.port += 1;
          this.server?.listen(this.port, "127.0.0.1");
        } else {
          console.error("[capture] Server error:", err);
          reject(err);
        }
      });
    });
  }

  public stop(): void {
    if (this.server) {
      this.server.close();
      this.server = null;
      console.log("[capture] Capture service stopped");
    }
    this.pool.destroyAll();
  }

  public async handleCapture(req: CaptureRequest): Promise<CaptureResponse> {
    const mode = req.mode || "preview";
    const width = req.width || 1280;
    const height = req.height || 900;

    if (mode === "app_window") {
      const mainWindow = this.getMainWindow();
      if (!mainWindow || mainWindow.isDestroyed()) {
        return { success: false, error: "Main window is not available or closed." };
      }
      try {
        const image = await mainWindow.webContents.capturePage();
        return this.processImage(image);
      } catch (err: any) {
        return { success: false, error: `Failed to capture main window: ${err?.message || err}` };
      }
    }

    // mode === "preview"
    const target = (req.target || "").trim();
    if (!target) {
      return { success: false, error: "Missing required 'target' parameter for preview capture." };
    }

    if (target.toLowerCase().startsWith("file://") || target.toLowerCase().startsWith("file:")) {
      return { success: false, error: "file:// protocol is strictly blocked for security." };
    }

    let parsedUrl: URL;
    try {
      parsedUrl = new URL(target);
    } catch {
      return { success: false, error: `Invalid URL target: '${target}'. file:// and relative file paths are blocked.` };
    }

    if (parsedUrl.protocol !== "https:" && parsedUrl.protocol !== "http:") {
      return { success: false, error: `Protocol '${parsedUrl.protocol}' is disallowed. Only http/https permitted.` };
    }

    if (isPrivateOrMetadataHost(parsedUrl.hostname)) {
      return { success: false, error: `Access to private, localhost, or metadata host '${parsedUrl.hostname}' is blocked.` };
    }

    const targetUrl = parsedUrl.href;
    let previewWin: BrowserWindow | null = null;
    try {
      previewWin = await this.pool.acquire(width, height);

      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => {
          resolve();
        }, 10000);

        previewWin!.webContents.once("did-finish-load", () => {
          clearTimeout(timeout);
          resolve();
        });

        previewWin!.webContents.once("did-fail-load", (_e, errorCode, errorDesc) => {
          clearTimeout(timeout);
          if (errorCode !== -3) {
            console.warn(`[capture] Warning: Preview load failed (${errorCode}): ${errorDesc}`);
          }
          resolve();
        });

        previewWin!.loadURL(targetUrl).catch((err) => {
          clearTimeout(timeout);
          reject(err);
        });
      });

      // Wait 1000ms for animations and layout settling
      await new Promise((resolve) => setTimeout(resolve, 1000));

      const image = await previewWin.webContents.capturePage();
      return this.processImage(image);
    } catch (err: any) {
      return { success: false, error: `Preview capture failed: ${err?.message || err}` };
    } finally {
      this.pool.release(previewWin);
    }
  }

  private processImage(image: Electron.NativeImage): CaptureResponse {
    const originalSize = image.getSize();
    let finalImage = image;

    // Resize capture to <= 1280px width
    if (originalSize.width > 1280) {
      const scale = 1280 / originalSize.width;
      const targetHeight = Math.round(originalSize.height * scale);
      finalImage = image.resize({ width: 1280, height: targetHeight, quality: "better" });
    }

    const finalSize = finalImage.getSize();
    const jpegBuffer = finalImage.toJPEG(80);
    const base64 = jpegBuffer.toString("base64");

    return {
      success: true,
      image_base64: base64,
      format: "image/jpeg",
      width: finalSize.width,
      height: finalSize.height,
    };
  }
}
