import { describe, it, expect, vi } from "vitest";

vi.mock("electron", () => ({
  app: { isPackaged: false, getPath: () => "mock-path" },
  dialog: { showErrorBox: vi.fn() },
}));

import { buildSpawnOptions } from "../../electron/services/backendProcess";

describe("Electron Backend Spawn Options Suite", () => {
  it("test_spawn_options_hide_window (windowsHide true, stdio piped)", () => {
    const opts = buildSpawnOptions();
    expect(opts.windowsHide).toBe(true);
    expect(opts.stdio).toEqual(["ignore", "pipe", "pipe"]);
  });

  it("test_win32_creation_flag_present", () => {
    const opts = buildSpawnOptions("win32");
    expect(opts.creationFlags).toBe(0x08000000); // CREATE_NO_WINDOW
    expect(opts.windowsHide).toBe(true);
  });

  it("test_unix_no_creation_flag", () => {
    const linuxOpts = buildSpawnOptions("linux");
    expect(linuxOpts.creationFlags).toBeUndefined();
    expect(linuxOpts.windowsHide).toBe(true);

    const darwinOpts = buildSpawnOptions("darwin");
    expect(darwinOpts.creationFlags).toBeUndefined();
    expect(darwinOpts.windowsHide).toBe(true);
  });

  it("test_stdio_pipes_preserved_for_token_parsing", () => {
    const env = { CODE_OS_SESSION_TOKEN: "mock-token", PORT: "8000" };
    const cwd = "D:/PROJECTS/CODE OS/backend";
    const opts = buildSpawnOptions("win32", env, cwd);

    // Stdio pipes MUST stay attached so SESSION_TOKEN stdout parsing and error detection work
    expect(opts.stdio).toHaveLength(3);
    expect(opts.stdio[0]).toBe("ignore");
    expect(opts.stdio[1]).toBe("pipe");
    expect(opts.stdio[2]).toBe("pipe");

    expect(opts.env).toEqual(env);
    expect(opts.cwd).toBe(cwd);
  });
});
