/**
 * src/__tests__/authenticated_sse.test.ts — Tests for Authenticated SSE Transport (AUD-010).
 *
 * Requirements:
 * 1. test_sse_helper_reconnects_and_cleans_up:
 *    - Mints scoped stream token via api.post(/api/auth/stream-token)
 *    - Attaches token to EventSource URL
 *    - Reconnects with exponential backoff on drop with fresh token
 *    - Cleanly unsubscribes and closes timers on close()
 * 2. test_no_eventsource_without_auth_in_stores:
 *    - Verifies teamStore, marathonStore, and agenticTerminalStore do not use unauthenticated raw `new EventSource`
 *    - Verifies all 3 use createAuthenticatedSSEStream
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as fs from "fs";
import * as path from "path";
import { createAuthenticatedSSEStream } from "../lib/sse";
import { api } from "../lib/api";

// ── Mock EventSource ─────────────────────────────────────────────────────────

class MockEventSource {
  url: string;
  onopen: ((evt: any) => void) | null = null;
  onmessage: ((evt: any) => void) | null = null;
  onerror: ((evt: any) => void) | null = null;
  listeners: Record<string, ((evt: any) => void)[]> = {};
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(name: string, fn: (evt: any) => void) {
    if (!this.listeners[name]) {
      this.listeners[name] = [];
    }
    this.listeners[name].push(fn);
  }

  removeEventListener(name: string, fn: (evt: any) => void) {
    if (this.listeners[name]) {
      this.listeners[name] = this.listeners[name].filter((l) => l !== fn);
    }
  }

  static instances: MockEventSource[] = [];
  static reset() {
    MockEventSource.instances = [];
  }
}

describe("AUD-010 Authenticated SSE Transport", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    MockEventSource.reset();
    (global as any).EventSource = MockEventSource;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // ── Test 3: SSE Helper Reconnects and Cleans Up ───────────────────────────
  it("test_sse_helper_reconnects_and_cleans_up: mints scoped tokens, reconnects with backoff, and tears down cleanly", async () => {
    vi.useFakeTimers();

    let tokenCounter = 0;
    const postSpy = vi.spyOn(api, "post").mockImplementation(async (url, body) => {
      if (url === "/api/auth/stream-token") {
        tokenCounter++;
        return { token: `scoped_token_${tokenCounter}` };
      }
      return {};
    });

    const onOpen = vi.fn();
    const onError = vi.fn();
    const onMessage = vi.fn();

    const stream = createAuthenticatedSSEStream({
      route: "/api/terminal/stream/term-123",
      baseDelayMs: 1000,
      maxDelayMs: 8000,
      onOpen,
      onError,
      onMessage,
    });

    // Initial token fetch runs asynchronously
    await vi.advanceTimersByTimeAsync(10);

    // Verify token was requested with correct route scope
    expect(postSpy).toHaveBeenCalledWith("/api/auth/stream-token", {
      route: "/api/terminal/stream/term-123",
    });

    // Verify EventSource instance was created with ?token=
    expect(MockEventSource.instances.length).toBe(1);
    const es1 = MockEventSource.instances[0];
    expect(es1.url).toContain("/api/terminal/stream/term-123");
    expect(es1.url).toContain("token=scoped_token_1");

    // Simulate successful open
    es1.onopen?.(new Event("open"));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(stream.getState()).toBe("connected");

    // Simulate connection drop (error)
    es1.onerror?.(new Event("error"));
    expect(onError).toHaveBeenCalledTimes(1);
    expect(es1.close).toHaveBeenCalledTimes(1);
    expect(stream.getState()).toBe("error");

    // Advance 999ms: reconnect delay is 1000ms, should not have reconnected yet
    await vi.advanceTimersByTimeAsync(999);
    expect(MockEventSource.instances.length).toBe(1);

    // Advance 1ms to complete backoff delay (1000ms)
    await vi.advanceTimersByTimeAsync(1);

    // Verify fresh token was requested for reconnection (token TTL <= 60s)
    expect(postSpy).toHaveBeenCalledTimes(2);
    expect(MockEventSource.instances.length).toBe(2);
    const es2 = MockEventSource.instances[1];
    expect(es2.url).toContain("token=scoped_token_2");

    // Now test teardown: call close() on stream
    stream.close();
    expect(stream.getState()).toBe("closed");
    expect(es2.close).toHaveBeenCalledTimes(1);

    // Advance time further to confirm no new reconnect attempts are scheduled
    await vi.advanceTimersByTimeAsync(30000);
    expect(MockEventSource.instances.length).toBe(2);
    expect(postSpy).toHaveBeenCalledTimes(2);
  });

  // ── Test 4: No Unauthenticated EventSource in Stores (Lint-style) ──────────
  it("test_no_eventsource_without_auth_in_stores: verifies stores do not use raw unauthenticated EventSource", () => {
    const storeFiles = [
      path.resolve(__dirname, "../features/ai/console/teamStore.ts"),
      path.resolve(__dirname, "../features/marathon/marathonStore.ts"),
      path.resolve(__dirname, "../features/terminal/agenticTerminalStore.ts"),
    ];

    for (const filePath of storeFiles) {
      expect(fs.existsSync(filePath)).toBe(true);
      const content = fs.readFileSync(filePath, "utf-8");

      // Verify no direct `new EventSource(` calls exist in any of the stores
      const directEventSourceMatch = /new\s+EventSource\s*\(/.test(content);
      expect(
        directEventSourceMatch,
        `Forbidden unauthenticated 'new EventSource(' found in ${path.basename(filePath)}`
      ).toBe(false);

      // Verify each store imports and uses createAuthenticatedSSEStream
      expect(content).toContain("createAuthenticatedSSEStream");
    }
  });
});
