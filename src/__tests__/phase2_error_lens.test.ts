import { describe, expect, it } from "vitest";
import {
  parseDiagnostics,
  isPathInWorkspace,
  resolveWorkspaceRelativePath,
  type ParsedDiagnostic,
} from "../features/editor/errorLensParser";

describe("Phase 2: Error Lens Diagnostics Parsers", () => {
  const ws = "/projects/my-app";

  it("parses pytest traceback and failure lines into diagnostics", () => {
    const pytestOutput = `
============================= test session starts =============================
collecting ... collected 2 items

tests/test_auth.py::test_login_invalid_password FAILED
Traceback (most recent call last):
  File "/projects/my-app/tests/test_auth.py", line 42, in test_login_invalid_password
    assert response.status_code == 401
E   assert 500 == 401
E    +  where 500 = response.status_code
=========================== short test summary info ===========================
FAILED tests/test_auth.py::test_login_invalid_password - assert 500 == 401
============================== 1 failed in 0.42s ==============================
`;

    const diags = parseDiagnostics(pytestOutput, ws);
    expect(diags.length).toBeGreaterThan(0);
    const diag = diags[0];
    expect(diag.filePath).toBe("tests/test_auth.py");
    expect(diag.line).toBe(42);
    expect(diag.severity).toBe("error");
    expect(diag.message).toContain("assert 500 == 401");
    expect(diag.source).toBe("pytest");
  });

  it("parses TypeScript compiler (tsc) diagnostics in both paren and colon formats", () => {
    const tscOutput = `
src/app.ts(15,8): error TS2322: Type 'string' is not assignable to type 'number'.
src/components/Header.tsx:28:14 - error TS2304: Cannot find name 'useUserData'.
src/utils/logger.ts(5,1): warning TS2305: Module '"fs"' has no exported member 'sync'.
`;

    const diags = parseDiagnostics(tscOutput, ws);
    expect(diags).toHaveLength(3);

    // Paren format error
    expect(diags[0].filePath).toBe("src/app.ts");
    expect(diags[0].line).toBe(15);
    expect(diags[0].column).toBe(8);
    expect(diags[0].severity).toBe("error");
    expect(diags[0].message).toContain("TS2322");
    expect(diags[0].source).toBe("tsc");

    // Colon format error
    expect(diags[1].filePath).toBe("src/components/Header.tsx");
    expect(diags[1].line).toBe(28);
    expect(diags[1].column).toBe(14);
    expect(diags[1].severity).toBe("error");
    expect(diags[1].message).toContain("TS2304");

    // Warning
    expect(diags[2].filePath).toBe("src/utils/logger.ts");
    expect(diags[2].line).toBe(5);
    expect(diags[2].severity).toBe("warning");
  });

  it("parses GCC / Clang compiler errors and warnings", () => {
    const gccOutput = `
src/main.cpp:12:5: error: 'cout' was not declared in this scope; did you mean 'std::cout'?
src/utils.cpp:45:10: warning: unused variable 'unusedCount' [-Wunused-variable]
/usr/include/stdio.h:10:2: error: standard library error
`;

    const diags = parseDiagnostics(gccOutput, ws);
    // /usr/include/stdio.h should be filtered out (system path)
    expect(diags).toHaveLength(2);

    expect(diags[0].filePath).toBe("src/main.cpp");
    expect(diags[0].line).toBe(12);
    expect(diags[0].column).toBe(5);
    expect(diags[0].severity).toBe("error");
    expect(diags[0].message).toContain("'cout' was not declared in this scope");
    expect(diags[0].source).toBe("gcc");

    expect(diags[1].filePath).toBe("src/utils.cpp");
    expect(diags[1].line).toBe(45);
    expect(diags[1].severity).toBe("warning");
  });

  it("filters out paths outside workspace and standard library files", () => {
    expect(isPathInWorkspace("/usr/include/stdlib.h", ws)).toBe(false);
    expect(isPathInWorkspace("C:/Python311/Lib/site-packages/pytest.py", ws)).toBe(false);
    expect(isPathInWorkspace("/projects/other-project/file.ts", ws)).toBe(false);
    expect(isPathInWorkspace("../outside/file.ts", ws)).toBe(false);

    expect(isPathInWorkspace("/projects/my-app/src/index.ts", ws)).toBe(true);
    expect(isPathInWorkspace("src/index.ts", ws)).toBe(true);
  });

  it("clears stale diagnostics on file edit simulation", () => {
    const store: Record<string, ParsedDiagnostic[]> = {
      "src/index.ts": [
        { filePath: "src/index.ts", line: 10, column: 1, severity: "error", message: "syntax error", source: "tsc" },
      ],
      "src/utils.ts": [
        { filePath: "src/utils.ts", line: 5, column: 1, severity: "warning", message: "unused var", source: "tsc" },
      ],
    };

    // Stale handling function: clear markers for a file when edited
    const clearFileDiagnostics = (filePath: string) => {
      delete store[filePath];
    };

    clearFileDiagnostics("src/index.ts");
    expect(store["src/index.ts"]).toBeUndefined();
    expect(store["src/utils.ts"]).toHaveLength(1);
  });
});
