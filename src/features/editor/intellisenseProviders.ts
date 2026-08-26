import type * as Monaco from "monaco-editor";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import type { FileNode } from "../../types/api";

let activeDisposables: Monaco.IDisposable[] = [];

const COMMON_HTML_TAGS = [
  "div", "span", "p", "a", "button", "input", "form", "label", "select", "option", "textarea",
  "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table", "thead", "tbody", "tr", "td", "th",
  "section", "article", "header", "footer", "nav", "main", "aside", "figure", "figcaption",
  "img", "video", "audio", "canvas", "iframe", "pre", "code", "blockquote", "hr", "br",
  "script", "style", "link", "meta",
];

const COMMON_SVG_TAGS = [
  "svg", "path", "g", "circle", "rect", "line", "polyline", "polygon", "text", "defs", "use",
  "clipPath", "mask", "pattern", "linearGradient", "radialGradient", "stop", "symbol",
];

const VOID_TAGS = new Set(["img", "input", "br", "hr", "meta", "link"]);

const COMMON_CPP_HEADERS = [
  "iostream", "vector", "string", "memory", "algorithm", "cstdio", "cstdlib", "cmath",
  "map", "set", "unordered_map", "unordered_set", "utility", "chrono", "thread", "mutex",
  "fstream", "sstream", "cassert", "cstring", "cstdint", "optional", "variant", "tuple",
  "iterator", "functional", "type_traits", "limits", "numeric", "regex", "exception",
];

function collectWorkspaceHeaders(node: FileNode | null): string[] {
  if (!node) return [];
  const results: string[] = [];
  const walk = (n: FileNode) => {
    if (n.type === "file") {
      const lower = n.name.toLowerCase();
      if (lower.endsWith(".h") || lower.endsWith(".hpp") || lower.endsWith(".hxx") || lower.endsWith(".hh")) {
        results.push(n.name);
      }
    }
    for (const child of n.children ?? []) {
      walk(child);
    }
  };
  walk(node);
  return Array.from(new Set(results));
}

function collectWorkspaceFiles(node: FileNode | null): string[] {
  if (!node) return [];
  const results: string[] = [];
  const walk = (n: FileNode) => {
    results.push(n.path);
    for (const child of n.children ?? []) {
      walk(child);
    }
  };
  walk(node);
  return results;
}

export function registerIntellisenseProviders(monaco: typeof Monaco): Monaco.IDisposable[] {
  disposeIntellisenseProviders();

  const disposables: Monaco.IDisposable[] = [];

  // 1. HTML / XML / SVG Tag Suggestions
  const htmlProvider = monaco.languages.registerCompletionItemProvider("html", {
    triggerCharacters: ["<"],
    provideCompletionItems(model, position) {
      const textUntilPosition = model.getValueInRange({
        startLineNumber: position.lineNumber,
        startColumn: 1,
        endLineNumber: position.lineNumber,
        endColumn: position.column,
      });

      if (!textUntilPosition.endsWith("<")) {
        return { suggestions: [] };
      }

      const suggestions: Monaco.languages.CompletionItem[] = COMMON_HTML_TAGS.map((tag) => ({
        label: `<${tag}>`,
        kind: monaco.languages.CompletionItemKind.Snippet,
        detail: `HTML element: <${tag}>`,
        insertText: VOID_TAGS.has(tag) ? `${tag} $1/>` : `${tag}>$1</${tag}>`,
        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
        range: {
          startLineNumber: position.lineNumber,
          startColumn: position.column,
          endLineNumber: position.lineNumber,
          endColumn: position.column,
        },
      }));

      return { suggestions };
    },
  });
  disposables.push(htmlProvider);

  // SVG Provider
  const xmlProvider = monaco.languages.registerCompletionItemProvider("xml", {
    triggerCharacters: ["<"],
    provideCompletionItems(model, position) {
      const textUntilPosition = model.getValueInRange({
        startLineNumber: position.lineNumber,
        startColumn: 1,
        endLineNumber: position.lineNumber,
        endColumn: position.column,
      });

      if (!textUntilPosition.endsWith("<")) {
        return { suggestions: [] };
      }

      const allTags = [...COMMON_SVG_TAGS, ...COMMON_HTML_TAGS];
      const suggestions: Monaco.languages.CompletionItem[] = allTags.map((tag) => ({
        label: `<${tag}>`,
        kind: monaco.languages.CompletionItemKind.Snippet,
        detail: `Tag: <${tag}>`,
        insertText: `${tag}>$1</${tag}>`,
        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
        range: {
          startLineNumber: position.lineNumber,
          startColumn: position.column,
          endLineNumber: position.lineNumber,
          endColumn: position.column,
        },
      }));

      return { suggestions };
    },
  });
  disposables.push(xmlProvider);

  // 2. C / C++ (#include) Headers Suggestion
  const cppProvider = monaco.languages.registerCompletionItemProvider("cpp", {
    triggerCharacters: ['"', "<", "/", "\\"],
    provideCompletionItems(model, position) {
      const lineContent = model.getLineContent(position.lineNumber);
      const textUntilPosition = lineContent.substring(0, position.column - 1);

      const includeQuoteMatch = textUntilPosition.match(/#include\s*"([^"]*)$/);
      const includeAngleMatch = textUntilPosition.match(/#include\s*<([^>]*)$/);

      if (!includeQuoteMatch && !includeAngleMatch) {
        return { suggestions: [] };
      }

      const isQuote = Boolean(includeQuoteMatch);
      const suggestions: Monaco.languages.CompletionItem[] = [];

      // Workspace headers
      const tree = useWorkspaceStore.getState().fileTree;
      const wsHeaders = collectWorkspaceHeaders(tree);

      for (const h of wsHeaders) {
        suggestions.push({
          label: h,
          kind: monaco.languages.CompletionItemKind.File,
          detail: "Workspace Header",
          insertText: isQuote ? `${h}"` : `${h}>`,
          range: {
            startLineNumber: position.lineNumber,
            startColumn: position.column,
            endLineNumber: position.lineNumber,
            endColumn: position.column,
          },
          sortText: isQuote ? `0_${h}` : `1_${h}`,
        });
      }

      // Standard Library Headers
      for (const stdH of COMMON_CPP_HEADERS) {
        suggestions.push({
          label: stdH,
          kind: monaco.languages.CompletionItemKind.Module,
          detail: "C++ Standard Library",
          insertText: isQuote ? `${stdH}"` : `${stdH}>`,
          range: {
            startLineNumber: position.lineNumber,
            startColumn: position.column,
            endLineNumber: position.lineNumber,
            endColumn: position.column,
          },
          sortText: isQuote ? `1_${stdH}` : `0_${stdH}`,
        });
      }

      return { suggestions };
    },
  });
  disposables.push(cppProvider);

  // 3. TypeScript / JavaScript Import Paths Suggestion
  const tsImportProvider = monaco.languages.registerCompletionItemProvider("typescript", {
    triggerCharacters: ['"', "'", "/", "."],
    provideCompletionItems(model, position) {
      const lineContent = model.getLineContent(position.lineNumber);
      const textUntilPosition = lineContent.substring(0, position.column - 1);

      // Match import/from/require relative paths e.g. from "./ or import("./
      const importMatch = textUntilPosition.match(/(?:from|import|require)\s*\(?['"](\.[^'"]*)$/);
      if (!importMatch) {
        return { suggestions: [] };
      }

      const typedPrefix = importMatch[1]; // e.g. "./" or "../"
      const suggestions: Monaco.languages.CompletionItem[] = [];

      const currentPath = model.uri.path;
      const currentDir = currentPath.replace(/[\\/][^\\/]+$/, "");
      const tree = useWorkspaceStore.getState().fileTree;
      const allFiles = collectWorkspaceFiles(tree);

      for (const fullPath of allFiles) {
        const normFull = fullPath.replace(/\\/g, "/");
        const normDir = currentDir.replace(/\\/g, "/");

        if (normFull.startsWith(normDir) && normFull !== currentPath.replace(/\\/g, "/")) {
          const relativePart = normFull.substring(normDir.length).replace(/^\/+/, "");
          const fileStem = relativePart.replace(/\.(tsx?|jsx?|d\.ts)$/, "");

          suggestions.push({
            label: `./${fileStem}`,
            kind: monaco.languages.CompletionItemKind.File,
            detail: `Workspace File (${relativePart})`,
            insertText: `./${fileStem}`,
            range: {
              startLineNumber: position.lineNumber,
              startColumn: position.column - typedPrefix.length,
              endLineNumber: position.lineNumber,
              endColumn: position.column,
            },
          });
        }
      }

      return { suggestions };
    },
  });
  disposables.push(tsImportProvider);

  activeDisposables = disposables;
  return disposables;
}

export function disposeIntellisenseProviders(): void {
  for (const d of activeDisposables) {
    try {
      d.dispose();
    } catch {
      // Ignore disposal errors
    }
  }
  activeDisposables = [];
}

export function areIntellisenseProvidersActive(): boolean {
  return activeDisposables.length > 0;
}
