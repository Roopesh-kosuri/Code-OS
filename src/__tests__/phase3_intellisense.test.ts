import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  registerIntellisenseProviders,
  disposeIntellisenseProviders,
  areIntellisenseProvidersActive,
} from "../features/editor/intellisenseProviders";
import { useWorkspaceStore } from "../stores/workspaceStore";

describe("Phase 3: Monaco Workers & Custom IntelliSense Providers", () => {
  let registeredProviders: Record<string, any> = {};

  const mockMonaco: any = {
    languages: {
      CompletionItemKind: {
        Snippet: 15,
        File: 17,
        Module: 9,
      },
      CompletionItemInsertTextRule: {
        InsertAsSnippet: 4,
      },
      registerCompletionItemProvider: vi.fn((lang: string, provider: any) => {
        registeredProviders[lang] = provider;
        return {
          dispose: vi.fn(() => {
            delete registeredProviders[lang];
          }),
        };
      }),
    },
  };

  const mockWorkspace: any = {
    name: "demo-project",
    path: "/home/project",
    type: "directory" as const,
    children: [
      {
        name: "math_utils.h",
        path: "/home/project/math_utils.h",
        type: "file" as const,
      },
      {
        name: "components",
        path: "/home/project/components",
        type: "directory" as const,
        children: [
          {
            name: "Button.tsx",
            path: "/home/project/components/Button.tsx",
            type: "file" as const,
          },
          {
            name: "Modal.tsx",
            path: "/home/project/components/Modal.tsx",
            type: "file" as const,
          },
        ],
      },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    registeredProviders = {};
    disposeIntellisenseProviders();
    useWorkspaceStore.setState({
      fileTree: mockWorkspace,
      fileTrees: { [mockWorkspace.path]: mockWorkspace },
    });
  });

  it("registers providers for html, xml, cpp, and typescript", () => {
    registerIntellisenseProviders(mockMonaco);
    expect(mockMonaco.languages.registerCompletionItemProvider).toHaveBeenCalledWith("html", expect.anything());
    expect(mockMonaco.languages.registerCompletionItemProvider).toHaveBeenCalledWith("xml", expect.anything());
    expect(mockMonaco.languages.registerCompletionItemProvider).toHaveBeenCalledWith("cpp", expect.anything());
    expect(mockMonaco.languages.registerCompletionItemProvider).toHaveBeenCalledWith("typescript", expect.anything());
    expect(areIntellisenseProvidersActive()).toBe(true);
  });

  it("provides HTML/XML tag completions on '<' trigger", () => {
    registerIntellisenseProviders(mockMonaco);
    const htmlProvider = registeredProviders["html"];
    expect(htmlProvider.triggerCharacters).toContain("<");

    const mockModel = {
      getValueInRange: vi.fn().mockReturnValue("<"),
    };
    const position = { lineNumber: 1, column: 2 };

    const result = htmlProvider.provideCompletionItems(mockModel, position);
    expect(result.suggestions.length).toBeGreaterThan(20);

    const divTag = result.suggestions.find((s: any) => s.label === "<div>");
    expect(divTag).toBeDefined();
    expect(divTag.insertText).toBe("div>$1</div>");
    expect(divTag.insertTextRules).toBe(mockMonaco.languages.CompletionItemInsertTextRule.InsertAsSnippet);

    const inputTag = result.suggestions.find((s: any) => s.label === "<input>");
    expect(inputTag).toBeDefined();
    expect(inputTag.insertText).toBe("input $1/>"); // void tag
  });

  it("provides C++ header completions on '#include \"' and '#include <'", () => {
    registerIntellisenseProviders(mockMonaco);
    const cppProvider = registeredProviders["cpp"];

    // 1. Quoted include: suggests workspace headers first
    const mockModelQuote = {
      getLineContent: vi.fn().mockReturnValue('#include "'),
    };
    const quoteResult = cppProvider.provideCompletionItems(mockModelQuote, { lineNumber: 1, column: 11 });
    expect(quoteResult.suggestions.length).toBeGreaterThan(0);

    const wsHeader = quoteResult.suggestions.find((s: any) => s.label === "math_utils.h");
    expect(wsHeader).toBeDefined();
    expect(wsHeader.detail).toBe("Workspace Header");
    expect(wsHeader.insertText).toBe('math_utils.h"');

    // 2. Angle bracket include: suggests standard library headers
    const mockModelAngle = {
      getLineContent: vi.fn().mockReturnValue("#include <"),
    };
    const angleResult = cppProvider.provideCompletionItems(mockModelAngle, { lineNumber: 1, column: 11 });
    const iostreamHeader = angleResult.suggestions.find((s: any) => s.label === "iostream");
    expect(iostreamHeader).toBeDefined();
    expect(iostreamHeader.detail).toBe("C++ Standard Library");
    expect(iostreamHeader.insertText).toBe("iostream>");
  });

  it("provides relative file path completions for TypeScript imports", () => {
    registerIntellisenseProviders(mockMonaco);
    const tsProvider = registeredProviders["typescript"];

    const mockModel = {
      uri: { path: "/home/project/components/Main.tsx" },
      getLineContent: vi.fn().mockReturnValue('import { Button } from "./'),
    };
    const result = tsProvider.provideCompletionItems(mockModel, { lineNumber: 1, column: 27 });
    expect(result.suggestions.length).toBeGreaterThan(0);

    const buttonImport = result.suggestions.find((s: any) => s.label === "./Button");
    expect(buttonImport).toBeDefined();
    expect(buttonImport.insertText).toBe("./Button");
  });

  it("properly disposes all providers when toggled off", () => {
    registerIntellisenseProviders(mockMonaco);
    expect(areIntellisenseProvidersActive()).toBe(true);

    disposeIntellisenseProviders();
    expect(areIntellisenseProvidersActive()).toBe(false);
    expect(Object.keys(registeredProviders).length).toBe(0);
  });
});
