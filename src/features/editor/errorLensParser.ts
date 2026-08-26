export interface ParsedDiagnostic {
  filePath: string;
  line: number;
  column: number;
  severity: "error" | "warning" | "info";
  message: string;
  source: "pytest" | "tsc" | "gcc" | "generic";
}

// Regex patterns for toolchain diagnostics (line length capped at 500 chars)
const PYTEST_TRACEBACK_RE = /File\s+"([^"]+)",\s+line\s+(\d+)/;
const PYTEST_FAILED_RE = /^(?:E\s+|FAILED\s+)(.+)$/;

const TSC_PAREN_RE = /^([^\s(:]+)\((\d+),(\d+)\):\s*(error|warning)\s*(TS\d+:.*)$/i;
const TSC_COLON_RE = /^([^\s:]+):(\d+):(\d+)\s*-\s*(error|warning)\s*(TS\d+:.*)$/i;

const GCC_CLANG_RE = /^([^\s:]+):(\d+):(\d+):\s*(error|warning|fatal error|note):\s*(.*)$/i;

function normalizePathStr(p: string): string {
  return p.replace(/\\/g, "/").replace(/\/+/g, "/").trim();
}

export function isPathInWorkspace(filePath: string, workspacePath: string): boolean {
  if (!filePath || !workspacePath) return false;
  const normFile = normalizePathStr(filePath).toLowerCase();
  const normWs = normalizePathStr(workspacePath).toLowerCase().replace(/\/$/, "");

  // Ignore system / standard library / venv paths
  if (
    normFile.includes("site-packages") ||
    normFile.includes("python3") ||
    normFile.includes("/usr/include") ||
    normFile.includes("/usr/lib") ||
    normFile.includes("node_modules")
  ) {
    return false;
  }

  // Relative path (e.g. "src/index.ts", "tests/test_main.py")
  if (!normFile.startsWith("/") && !/^[a-z]:\//i.test(normFile)) {
    return !normFile.startsWith("../");
  }

  return normFile.startsWith(normWs);
}

export function resolveWorkspaceRelativePath(filePath: string, workspacePath: string): string {
  const normFile = normalizePathStr(filePath);
  const normWs = normalizePathStr(workspacePath).replace(/\/$/, "");

  if (normFile.toLowerCase().startsWith(normWs.toLowerCase())) {
    const rel = normFile.slice(normWs.length).replace(/^\/+/, "");
    return rel;
  }
  return normFile;
}

export function parseDiagnostics(output: string, workspacePath: string): ParsedDiagnostic[] {
  if (!output) return [];

  const diagnostics: ParsedDiagnostic[] = [];
  const lines = output.split(/\r?\n/);
  const normWs = normalizePathStr(workspacePath);

  let currentPytestFile: string | null = null;
  let currentPytestLine: number | null = null;

  for (const rawLine of lines) {
    // Cap line length to 500 chars to avoid regex ReDoS or memory issues
    const line = rawLine.slice(0, 500).trim();
    if (!line) continue;

    // 1. Pytest traceback & failure lines
    const pytestTbMatch = line.match(PYTEST_TRACEBACK_RE);
    if (pytestTbMatch) {
      const candidatePath = pytestTbMatch[1];
      const candidateLine = parseInt(pytestTbMatch[2], 10);
      if (isPathInWorkspace(candidatePath, normWs)) {
        currentPytestFile = resolveWorkspaceRelativePath(candidatePath, normWs);
        currentPytestLine = candidateLine;
      }
      continue;
    }

    const pytestFailMatch = line.match(PYTEST_FAILED_RE);
    if (pytestFailMatch && currentPytestFile && currentPytestLine) {
      diagnostics.push({
        filePath: currentPytestFile,
        line: currentPytestLine,
        column: 1,
        severity: "error",
        message: pytestFailMatch[1].trim(),
        source: "pytest",
      });
      continue;
    }

    // 2. TypeScript compiler (tsc) diagnostics
    // Format A: file.ts(12,5): error TS2322: Type 'string' is not assignable...
    const tscParenMatch = line.match(TSC_PAREN_RE);
    if (tscParenMatch) {
      const candidatePath = tscParenMatch[1];
      if (isPathInWorkspace(candidatePath, normWs)) {
        diagnostics.push({
          filePath: resolveWorkspaceRelativePath(candidatePath, normWs),
          line: parseInt(tscParenMatch[2], 10),
          column: parseInt(tscParenMatch[3], 10),
          severity: tscParenMatch[4].toLowerCase() === "warning" ? "warning" : "error",
          message: tscParenMatch[5].trim(),
          source: "tsc",
        });
      }
      continue;
    }

    // Format B: file.ts:12:5 - error TS2322: ...
    const tscColonMatch = line.match(TSC_COLON_RE);
    if (tscColonMatch) {
      const candidatePath = tscColonMatch[1];
      if (isPathInWorkspace(candidatePath, normWs)) {
        diagnostics.push({
          filePath: resolveWorkspaceRelativePath(candidatePath, normWs),
          line: parseInt(tscColonMatch[2], 10),
          column: parseInt(tscColonMatch[3], 10),
          severity: tscColonMatch[4].toLowerCase() === "warning" ? "warning" : "error",
          message: tscColonMatch[5].trim(),
          source: "tsc",
        });
      }
      continue;
    }

    // 3. GCC / Clang compiler diagnostics
    // Format: file.cpp:12:5: error: 'x' was not declared in this scope
    const gccMatch = line.match(GCC_CLANG_RE);
    if (gccMatch) {
      const candidatePath = gccMatch[1];
      if (isPathInWorkspace(candidatePath, normWs)) {
        const sevStr = gccMatch[4].toLowerCase();
        const severity = sevStr.includes("error")
          ? "error"
          : sevStr.includes("warning")
          ? "warning"
          : "info";
        diagnostics.push({
          filePath: resolveWorkspaceRelativePath(candidatePath, normWs),
          line: parseInt(gccMatch[2], 10),
          column: parseInt(gccMatch[3], 10),
          severity,
          message: gccMatch[5].trim(),
          source: "gcc",
        });
      }
      continue;
    }
  }

  return diagnostics;
}
