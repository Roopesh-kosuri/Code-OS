/**
 * src/__tests__/aud_013_enhancer_stale_response.test.ts
 *
 * AUD-013: Prompt enhancer stale-response race condition.
 * When slow classification for an old draft (e.g. "hi") returns AFTER a new
 * draft (e.g. "fix the bug") has been typed, the old response must be discarded
 * via revision ID and/or AbortController gate, so out-of-order completions
 * cannot change the current-input UI.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Map to hold pending resolvers for deferred responses
type Resolver = (val: any) => void;
const pendingCalls: { url: string; body: any; resolve: Resolver; signal?: AbortSignal }[] = [];

vi.mock("../lib/api", () => ({
  api: {
    post: vi.fn(async (url: string, body?: any, _query?: any, options?: any) => {
      return new Promise((resolve) => {
        pendingCalls.push({ url, body, resolve, signal: options?.signal });
      });
    }),
    get: vi.fn(async () => ({})),
  },
  API_BASE: "http://127.0.0.1:8000",
}));

describe("AUD-013: Prompt Enhancer Stale-Response Race Gate", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    pendingCalls.length = 0;
    localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("test_enhancer_stale_response_discarded: out-of-order A response cannot overwrite B state", async () => {
    const { useIntelligenceStore } = await import("../stores/intelligenceStore");
    useIntelligenceStore.getState().reset();

    // 1. User types "hi"
    useIntelligenceStore.getState().classifyOnInput("hi");

    // 2. Advance 600ms to trigger debounce for "hi"
    vi.advanceTimersByTime(600);
    expect(pendingCalls.length).toBe(1);
    expect(pendingCalls[0].body.prompt).toBe("hi");
    const callA = pendingCalls[0];

    // 3. User immediately types "fix the bug" before "hi" completes
    useIntelligenceStore.getState().classifyOnInput("fix the bug");

    // 4. Advance 600ms to trigger debounce for "fix the bug"
    vi.advanceTimersByTime(600);
    expect(pendingCalls.length).toBe(2);
    expect(pendingCalls[1].body.prompt).toBe("fix the bug");
    const callB = pendingCalls[1];

    // 5. Old response A finishes now (deferred/out-of-order)
    callA.resolve({
      quality: "weak",
      score: 30,
      reasons: ["Too short"],
    });
    await vi.advanceTimersByTimeAsync(0);

    // Invariant: "hi" must have been discarded! Store must NOT reflect "hi"
    const stateAfterA = useIntelligenceStore.getState();
    expect(stateAfterA.originalPrompt).not.toBe("hi");

    // 7. Newer response B finishes
    callB.resolve({
      quality: "weak",
      score: 40,
      reasons: ["Ambiguous target"],
    });
    await vi.advanceTimersByTimeAsync(0);

    // Invariant: Store reflects "fix the bug"
    const stateAfterB = useIntelligenceStore.getState();
    expect(stateAfterB.originalPrompt).toBe("fix the bug");
    expect(stateAfterB.showBar).toBe(true);
  });

  it("test_empty_input_cancels_and_discards_in_flight_classification", async () => {
    const { useIntelligenceStore } = await import("../stores/intelligenceStore");
    useIntelligenceStore.getState().reset();

    // Type "something", debounce fires
    useIntelligenceStore.getState().classifyOnInput("something");
    vi.advanceTimersByTime(600);
    expect(pendingCalls.length).toBe(1);
    const call = pendingCalls[0];

    // Clear input before response arrives
    useIntelligenceStore.getState().classifyOnInput("");

    // Old response resolves
    call.resolve({ quality: "weak", score: 20 });
    await Promise.resolve();

    // Must remain hidden and empty
    const state = useIntelligenceStore.getState();
    expect(state.showBar).toBe(false);
    expect(state.originalPrompt).toBe("");
  });
});
