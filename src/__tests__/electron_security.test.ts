import { describe, it, expect } from "vitest";
import { validateExternalUrl } from "../../electron/utils/urlValidator";

describe("Electron URL Scheme Validation (FIX M8)", () => {
  it("allows standard web and email protocols", () => {
    expect(validateExternalUrl("https://github.com")).toBe(true);
    expect(validateExternalUrl("http://127.0.0.1:5176")).toBe(true);
    expect(validateExternalUrl("http://localhost:3000")).toBe(true);
    expect(validateExternalUrl("mailto:support@code-os.dev")).toBe(true);
  });

  it("blocks dangerous file, script, and custom protocols", () => {
    expect(validateExternalUrl("file:///C:/Windows/System32/cmd.exe")).toBe(false);
    expect(validateExternalUrl("file:///etc/passwd")).toBe(false);
    expect(validateExternalUrl("javascript:alert(1)")).toBe(false);
    expect(validateExternalUrl("data:text/html,<script>alert(1)</script>")).toBe(false);
    expect(validateExternalUrl("vbscript:MsgBox(1)")).toBe(false);
    expect(validateExternalUrl("custom-proto://execute")).toBe(false);
  });

  it("handles malformed URLs safely", () => {
    expect(validateExternalUrl("")).toBe(false);
    expect(validateExternalUrl("not-a-valid-url")).toBe(false);
  });
});
