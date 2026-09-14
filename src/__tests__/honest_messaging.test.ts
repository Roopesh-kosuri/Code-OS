import { describe, it, expect } from "vitest";
import { getTaxonomyTip } from "../stores/aiStore";

describe("Honest Error Messaging (Phase 10.10 E4)", () => {
  it("returns token accounting tip when tokenizer dependency is missing, not compaction tip", () => {
    const errorMessages = [
      "Payload governance fail-closed: token accounting dependency missing (tiktoken unavailable in closed governor mode). Run 'pip install tiktoken' to resolve.",
      "Payload governance fail-closed: exact tokenizer unavailable; refusing to estimate request payload.",
      "token accounting dependency missing",
      "fail_closed: tokenizer unavailable",
      "Missing tiktoken dependency",
    ];

    for (const msg of errorMessages) {
      const tip = getTaxonomyTip("openai", msg);
      expect(tip).toContain("Token accounting dependency missing");
      expect(tip).toContain("pip install tiktoken");
      expect(tip).not.toContain("Context window limit reached");
      expect(tip).not.toContain("compacted");
    }
  });

  it("returns compaction tip ONLY when context window limit/compaction actually triggers", () => {
    const contextOverflowTip = getTaxonomyTip("openai", "Request exceeds maximum context length", "context_overflow");
    expect(contextOverflowTip).toContain("Context window limit reached. The conversation history was compacted.");

    const explicitContextTip = getTaxonomyTip("openai", "context window overflow occurred");
    expect(explicitContextTip).toContain("Context window limit reached. The conversation history was compacted.");
  });

  it("does not trigger compaction tip on generic errors containing the word token", () => {
    const genericTokenMsg = "Invalid API token provided for service";
    const tip = getTaxonomyTip("openai", genericTokenMsg);
    expect(tip).not.toContain("Context window limit reached");
    expect(tip).not.toContain("compacted");
  });
});
