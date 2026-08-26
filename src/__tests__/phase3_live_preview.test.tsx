import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import React from "react";
import { LivePreviewPanel, isValidPreviewUrl } from "../features/preview/LivePreviewPanel";

describe("Phase 3: Live Preview Panel for Server Sessions", () => {
  it("strictly validates preview URLs allowing only localhost and 127.0.0.1", () => {
    // Valid localhost and loopback URLs
    expect(isValidPreviewUrl("http://localhost:3000")).toBe(true);
    expect(isValidPreviewUrl("http://localhost:5173/dashboard")).toBe(true);
    expect(isValidPreviewUrl("http://127.0.0.1:8000")).toBe(true);
    expect(isValidPreviewUrl("http://127.0.0.1:5176/docs")).toBe(true);
    expect(isValidPreviewUrl("https://localhost:8443")).toBe(true);

    // Rejected non-localhost and SSRF URLs
    expect(isValidPreviewUrl("http://192.168.1.100:8080")).toBe(false);
    expect(isValidPreviewUrl("http://10.0.0.1:3000")).toBe(false);
    expect(isValidPreviewUrl("http://169.254.169.254/latest/meta-data")).toBe(false);
    expect(isValidPreviewUrl("https://google.com")).toBe(false);
    expect(isValidPreviewUrl("http://malicious-site.com")).toBe(false);
    expect(isValidPreviewUrl("javascript:alert(1)")).toBe(false);
    expect(isValidPreviewUrl("file:///etc/passwd")).toBe(false);
  });

  it("renders live iframe when server is running with valid localhost URL", () => {
    render(<LivePreviewPanel initialUrl="http://127.0.0.1:5173" isServerRunning={true} />);

    const iframe = screen.getByTestId("preview-iframe") as HTMLIFrameElement;
    expect(iframe).toBeTruthy();
    expect(iframe.src).toBe("http://127.0.0.1:5173/");
    expect(iframe.getAttribute("sandbox")).toBe("allow-scripts allow-forms allow-same-origin");
  });

  it("displays server stopped state when server terminates", () => {
    render(<LivePreviewPanel initialUrl="http://127.0.0.1:5173" isServerRunning={false} />);

    expect(screen.getByTestId("preview-server-stopped")).toBeTruthy();
    expect(screen.getByText("Server Stopped")).toBeTruthy();
  });

  it("blocks navigation and displays security banner on non-localhost URL input", () => {
    render(<LivePreviewPanel initialUrl="http://127.0.0.1:5173" isServerRunning={true} />);

    const input = screen.getByTestId("preview-url-input");
    fireEvent.change(input, { target: { value: "http://192.168.1.50:8080" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    expect(screen.getByTestId("preview-security-error")).toBeTruthy();
    expect(screen.getByText(/Security Error: Only http:\/\/localhost or http:\/\/127\.0\.0\.1/i)).toBeTruthy();
  });

  it("triggers external browser launch on open external click", () => {
    const mockOpen = vi.fn();
    (window as any).codeOS = { openExternal: mockOpen };

    render(<LivePreviewPanel initialUrl="http://127.0.0.1:8000" isServerRunning={true} />);

    const externalBtn = screen.getByTestId("preview-external-btn");
    fireEvent.click(externalBtn);

    expect(mockOpen).toHaveBeenCalledWith("http://127.0.0.1:8000");
  });
});
