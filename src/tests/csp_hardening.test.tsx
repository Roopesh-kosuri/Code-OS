import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

describe("Content Security Policy Hardening (FIX M4)", () => {
  const rootDir = process.cwd();
  const indexHtml = fs.readFileSync(path.join(rootDir, "index.html"), "utf-8");
  const mainTs = fs.readFileSync(path.join(rootDir, "electron/main.ts"), "utf-8");
  const captureTs = fs.readFileSync(path.join(rootDir, "electron/services/captureService.ts"), "utf-8");

  it("test_csp_no_unsafe_eval", () => {
    // Both index.html and Electron main headers must not permit unsafe-eval in script-src
    expect(indexHtml).toContain("Content-Security-Policy");
    expect(indexHtml).not.toContain("'unsafe-eval'");

    expect(mainTs).toContain("Content-Security-Policy");
    expect(mainTs).not.toContain("'unsafe-eval'");
  });

  it("test_csp_no_unsafe_inline", () => {
    // script-src in index.html and main.ts must not contain unsafe-inline
    // Extract script-src directives
    const scriptSrcMatches = [
      ...indexHtml.matchAll(/script-src\s+([^;"]+)/gi),
      ...mainTs.matchAll(/script-src\s+([^;"]+)/gi),
    ];
    expect(scriptSrcMatches.length).toBeGreaterThan(0);
    for (const match of scriptSrcMatches) {
      const scriptSrc = match[1];
      expect(scriptSrc).not.toContain("'unsafe-inline'");
    }
  });

  it("test_csp_applied_to_all_windows", () => {
    // session.defaultSession.webRequest.onHeadersReceived must be registered in main.ts
    expect(mainTs).toContain("session.defaultSession.webRequest.onHeadersReceived");
    expect(mainTs).toContain('responseHeaders["Content-Security-Policy"]');

    // captureService.ts must also enforce Content-Security-Policy on offscreen windows
    expect(captureTs).toContain('responseHeaders["Content-Security-Policy"]');
  });
});

