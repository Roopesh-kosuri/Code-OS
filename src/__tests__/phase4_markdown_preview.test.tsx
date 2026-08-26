import { render, screen, act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import React from "react";
import { MarkdownPreview } from "../features/editor/MarkdownPreview";

describe("Phase 4: Markdown Preview Pane", () => {
  it("renders headings, code blocks, and GFM tables properly", () => {
    const mdContent = `
# Main Project Title

Here is a paragraph with **bold** text and [a link](https://codeos.ai).

| Feature | Status |
| :--- | :--- |
| Error Lens | Live |
| Preview | Active |

\`\`\`typescript
const greeting: string = "Hello CODE OS";
console.log(greeting);
\`\`\`
`;

    render(<MarkdownPreview content={mdContent} />);

    // Verify heading
    expect(screen.getByRole("heading", { level: 1 })).toBeTruthy();
    expect(screen.getByText("Main Project Title")).toBeTruthy();

    // Verify table elements
    expect(screen.getByText("Feature")).toBeTruthy();
    expect(screen.getByText("Error Lens")).toBeTruthy();
    expect(screen.getByText("Live")).toBeTruthy();

    // Verify code snippet
    expect(screen.getByText(/const greeting: string = "Hello CODE OS"/i)).toBeTruthy();
  });

  it("sanitizes raw HTML and does not execute or inject script elements", () => {
    const maliciousMd = `
# Safe Heading

<script>window.__xss_executed = true;</script>
<img src="invalid" onerror="alert(1)" />
`;

    render(<MarkdownPreview content={maliciousMd} />);

    expect(screen.getByText("Safe Heading")).toBeTruthy();
    // Verify script tag is not inserted as executable script element
    const scriptElements = document.querySelectorAll("script[src], script:not([type])");
    let hasInjectedScript = false;
    scriptElements.forEach((s) => {
      if (s.textContent?.includes("__xss_executed")) {
        hasInjectedScript = true;
      }
    });
    expect(hasInjectedScript).toBe(false);
    expect((window as any).__xss_executed).toBeUndefined();
  });

  it("debounces content changes", () => {
    vi.useFakeTimers();
    const { rerender } = render(<MarkdownPreview content="# Initial Title" />);

    expect(screen.getByText("Initial Title")).toBeTruthy();

    // Update content immediately
    rerender(<MarkdownPreview content="# Updated Title" />);

    // Before 300ms, debounced content should still be initial
    expect(screen.getByText("Initial Title")).toBeTruthy();

    // Advance timers by 300ms
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(screen.getByText("Updated Title")).toBeTruthy();
    vi.useRealTimers();
  });
});
