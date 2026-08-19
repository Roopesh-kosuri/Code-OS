/**
 * inlineCompletionProvider.ts — Monaco Inline AI Code Completion Provider
 *
 * Implements ghost-text autocomplete with:
 * - 350ms debounce and AbortController cancellation on keystrokes
 * - Budgeted context extraction (last 100 lines prefix, ~30 lines suffix)
 * - Safe Tab accept / Esc dismiss integration with Monaco
 * - Settings toggle check (persisted in settingsStore & localStorage)
 * - Global fetching indicator state
 */
import type * as monacoType from "monaco-editor";
import { create } from "zustand";
import { api } from "../../lib/api";
import { useSettingsStore } from "../../stores/settingsStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";

interface CompletionResponse {
  completion: string;
  model: string;
  latency_ms: number;
  input_tokens_est: number;
}

interface InlineCompletionStore {
  isFetching: boolean;
  setFetching: (isFetching: boolean) => void;
  lastLatencyMs: number | null;
  setLastLatencyMs: (ms: number | null) => void;
}

export const useInlineCompletionStore = create<InlineCompletionStore>((set) => ({
  isFetching: false,
  setFetching: (isFetching) => set({ isFetching }),
  lastLatencyMs: null,
  setLastLatencyMs: (lastLatencyMs) => set({ lastLatencyMs }),
}));

let activeAbortController: AbortController | null = null;
let providerDisposable: monacoType.IDisposable | null = null;

export function registerInlineCompletionProvider(monaco: typeof monacoType): monacoType.IDisposable {
  if (providerDisposable) {
    return providerDisposable;
  }

  providerDisposable = monaco.languages.registerInlineCompletionsProvider(
    { pattern: "**" },
    {
      provideInlineCompletions: async (model, position, _context, token) => {
        // 1. Check if inline completions are enabled in settings
        const settings = useSettingsStore.getState().settings;
        const isEnabled =
          settings["editor.inlineCompletionEnabled"] !== "false" &&
          localStorage.getItem("code-os:editor.inlineCompletion") !== "false";

        if (!isEnabled) {
          return { items: [] };
        }

        // 2. Abort previous in-flight request on new typing
        if (activeAbortController) {
          activeAbortController.abort();
          activeAbortController = null;
        }

        const abortController = new AbortController();
        activeAbortController = abortController;

        // 3. Debounce typing by 350ms before dispatching LLM request
        try {
          await new Promise<void>((resolve, reject) => {
            const timer = setTimeout(resolve, 350);

            token.onCancellationRequested(() => {
              clearTimeout(timer);
              abortController.abort();
              reject(new Error("Cancelled by Monaco token"));
            });

            abortController.signal.addEventListener("abort", () => {
              clearTimeout(timer);
              reject(new Error("Aborted by new keystroke"));
            });
          });
        } catch {
          return { items: [] };
        }

        if (token.isCancellationRequested || abortController.signal.aborted) {
          return { items: [] };
        }

        // 4. Extract budgeted context (100 lines before, 30 lines after)
        const lineCount = model.getLineCount();
        const cursorLine = position.lineNumber;
        const cursorCol = position.column;

        const startLine = Math.max(1, cursorLine - 100);
        const endLine = Math.min(lineCount, cursorLine + 30);

        const prefix = model.getValueInRange({
          startLineNumber: startLine,
          startColumn: 1,
          endLineNumber: cursorLine,
          endColumn: cursorCol,
        });

        const suffix = model.getValueInRange({
          startLineNumber: cursorLine,
          startColumn: cursorCol,
          endLineNumber: endLine,
          endColumn: model.getLineMaxColumn(endLine),
        });

        if (!prefix.trim() && !suffix.trim()) {
          return { items: [] };
        }

        // 5. Send completion request with active indicator
        useInlineCompletionStore.getState().setFetching(true);
        const workspace = useWorkspaceStore.getState().currentWorkspace || "";
        const filePath = model.uri.fsPath || model.uri.path || "";
        const language = model.getLanguageId() || "plaintext";

        try {
          const res = await api.post<CompletionResponse>(
            "/api/ai/completion",
            {
              workspace,
              path: filePath,
              language,
              prefix,
              suffix,
              max_tokens: 128,
            },
            undefined,
            { signal: abortController.signal }
          );

          if (token.isCancellationRequested || abortController.signal.aborted) {
            return { items: [] };
          }

          useInlineCompletionStore.getState().setLastLatencyMs(res.latency_ms || null);

          if (res.completion && res.completion.trim()) {
            return {
              items: [
                {
                  insertText: res.completion,
                  range: new monaco.Range(
                    position.lineNumber,
                    position.column,
                    position.lineNumber,
                    position.column
                  ),
                },
              ],
            };
          }
        } catch {
          // Silent guardrail: single attempt only, no UI errors on completion failure
        } finally {
          useInlineCompletionStore.getState().setFetching(false);
          if (activeAbortController === abortController) {
            activeAbortController = null;
          }
        }

        return { items: [] };
      },
      disposeInlineCompletions: () => {
        // No-op cleanup
      },
    }
  );

  return providerDisposable;
}
