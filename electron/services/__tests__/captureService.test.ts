// @vitest-environment node
import { describe, it, expect, beforeAll, afterAll, vi } from "vitest";

vi.mock("electron", () => ({
  app: { isPackaged: false, getPath: () => "/mock/path" },
  BrowserWindow: class MockBrowserWindow {
    isDestroyed() { return false; }
    webContents = {
      isLoading: () => false,
      session: { clearCache: async () => {} },
      capturePage: async () => ({
        getSize: () => ({ width: 100, height: 100 }),
        resize: () => ({ getSize: () => ({ width: 100, height: 100 }), toJPEG: () => Buffer.from("mock") }),
        toJPEG: () => Buffer.from("mock"),
      }),
      loadURL: async () => {},
      once: (_event: string, cb: any) => cb(),
      stop: () => {},
    };
    setSize() {}
    destroy() {}
  },
}));

import { CaptureService } from "../captureService";

describe("CaptureService Security Hardening (H2)", () => {
  const TEST_TOKEN = "a".repeat(64);
  const TEST_PORT = 5998;
  let service: CaptureService;

  beforeAll(async () => {
    service = new CaptureService(() => null, TEST_PORT, TEST_TOKEN);
    await service.start();
  });

  afterAll(() => {
    service.stop();
  });

  it("returns 401 when token is missing", async () => {
    const res = await fetch(`http://127.0.0.1:${TEST_PORT}/capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target: "https://example.com" }),
    });
    expect(res.status).toBe(401);
    const data = await res.json();
    expect(data.success).toBe(false);
    expect(data.error).toContain("Unauthorized");
  });

  it("returns 401 when token is invalid", async () => {
    const res = await fetch(`http://127.0.0.1:${TEST_PORT}/capture`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer invalid-token-value",
      },
      body: JSON.stringify({ target: "https://example.com" }),
    });
    expect(res.status).toBe(401);
  });

  it("rejects file:///etc/passwd with 400", async () => {
    const res = await fetch(`http://127.0.0.1:${TEST_PORT}/capture`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${TEST_TOKEN}`,
      },
      body: JSON.stringify({ target: "file:///etc/passwd" }),
    });
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.success).toBe(false);
    expect(data.error).toMatch(/file:\/\/ protocol is strictly blocked/);
  });

  it("rejects target http://127.0.0.1:8000 with 400", async () => {
    const res = await fetch(`http://127.0.0.1:${TEST_PORT}/capture`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${TEST_TOKEN}`,
      },
      body: JSON.stringify({ target: "http://127.0.0.1:8000" }),
    });
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.success).toBe(false);
  });

  it("rejects target http://169.254.169.254 with 400", async () => {
    const res = await fetch(`http://127.0.0.1:${TEST_PORT}/capture`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${TEST_TOKEN}`,
      },
      body: JSON.stringify({ target: "http://169.254.169.254" }),
    });
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.success).toBe(false);
  });

  it("response headers never contain Access-Control-Allow-Origin: *", async () => {
    const originsToTest = [
      undefined,
      "http://evil.com",
      "https://malicious-site.com",
      "*",
      "http://127.0.0.1:5176",
    ];

    for (const origin of originsToTest) {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        Authorization: `Bearer ${TEST_TOKEN}`,
      };
      if (origin) {
        headers["Origin"] = origin;
      }

      const res = await fetch(`http://127.0.0.1:${TEST_PORT}/capture`, {
        method: "POST",
        headers,
        body: JSON.stringify({ target: "file:///etc/passwd" }),
      });

      const allowOrigin = res.headers.get("access-control-allow-origin");
      expect(allowOrigin).not.toBe("*");
      if (origin === "http://127.0.0.1:5176") {
        expect(allowOrigin).toBe("http://127.0.0.1:5176");
      } else {
        expect(allowOrigin).toBeNull();
      }
    }
  });
});
