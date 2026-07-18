import { useState } from "react";
import { Replace, Search } from "lucide-react";

import { Button } from "../../components/ui/Button";
import { IconButton } from "../../components/ui/IconButton";
import { api } from "../../lib/api";
import { useEditorStore } from "../../stores/editorStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import type { SearchMatch } from "../../types/api";

export function SearchPanel() {
  const [query, setQuery] = useState("");
  const [replacement, setReplacement] = useState("");
  const [regex, setRegex] = useState(false);
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [wholeWord, setWholeWord] = useState(false);
  const [matches, setMatches] = useState<SearchMatch[]>([]);
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);
  const openFile = useEditorStore((state) => state.openFile);

  const runSearch = async () => {
    if (!workspace || !query) return;
    setMatches(await api.get<SearchMatch[]>("/api/search/text", { workspace: workspace.path, query, regex, case_sensitive: caseSensitive, whole_word: wholeWord }));
  };

  const runReplacePreview = async () => {
    if (!workspace || !query) return;
    const results = await api.post<{ path: string; replacements: number }[]>("/api/search/replace", {
      workspace: workspace.path,
      query,
      replacement,
      apply: false,
      regex,
      case_sensitive: caseSensitive,
      whole_word: wholeWord
    });
    setMatches(results.map((item) => ({ path: item.path, line: 0, column: 0, preview: `${item.replacements} replacements` })));
  };

  if (!workspace) {
    return (
      <section className="flex h-full flex-col items-center justify-center p-4 text-center space-y-2 select-none border-b border-surface-700 bg-surface-900">
        <Search size={22} className="text-slate-600 mb-1 animate-pulse" />
        <span className="text-xs text-slate-500">Open a workspace to search text.</span>
      </section>
    );
  }

  return (
    <section className="grid h-full min-h-0 w-full min-w-0 grid-cols-1 grid-rows-[auto_minmax(0,1fr)] border-b border-surface-700">
      <div className="space-y-2 border-b border-surface-700 p-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          <Search size={15} />
          Search
        </div>
        <input className="h-8 w-full min-w-0 rounded-md border-surface-700 bg-surface-850 text-sm text-slate-100" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find text" />
        <div className="flex gap-2">
          <input className="h-8 min-w-0 flex-1 rounded-md border-surface-700 bg-surface-850 text-sm text-slate-100" value={replacement} onChange={(event) => setReplacement(event.target.value)} placeholder="Replace with" />
          <IconButton label="Search" icon={<Search size={15} />} onClick={() => void runSearch()} disabled={!workspace} />
          <IconButton label="Preview replace" icon={<Replace size={15} />} onClick={() => void runReplacePreview()} disabled={!workspace} />
        </div>
        <div className="flex gap-3 text-xs text-slate-400">
          <label className="flex items-center gap-1"><input type="checkbox" checked={regex} onChange={(event) => setRegex(event.target.checked)} /> Regex</label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={caseSensitive} onChange={(event) => setCaseSensitive(event.target.checked)} /> Case</label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={wholeWord} onChange={(event) => setWholeWord(event.target.checked)} /> Word</label>
        </div>
      </div>
      <div className="min-h-0 overflow-auto p-2">
        {matches.map((match) => (
          <button key={`${match.path}-${match.line}-${match.preview}`} className="mb-1 block w-full rounded px-2 py-2 text-left text-xs text-slate-300 hover:bg-surface-800" onClick={() => void openFile(match.path)}>
            <div className="truncate text-slate-100">{match.path}</div>
            <div className="truncate text-slate-500">{match.line ? `Line ${match.line}: ` : ""}{match.preview}</div>
          </button>
        ))}
        {!matches.length ? <div className="p-2 text-sm text-slate-500">Search results appear here.</div> : null}
        <div className="px-2 pt-2">
          <Button
            variant="danger"
            disabled={!workspace || !query || !matches.length}
            onClick={async () => {
              if (!workspace) return;
              const fileCount = new Set(matches.map((m) => m.path)).size;
              let totalReplacements = 0;
              matches.forEach((m) => {
                const match = m.preview.match(/^(\d+) replacements/);
                if (match) {
                  totalReplacements += parseInt(match[1], 10);
                } else {
                  totalReplacements += 1;
                }
              });
              const msg = totalReplacements > 1
                ? `Apply replacement in ${fileCount} files (${totalReplacements} matches)? This will overwrite files on disk.`
                : `Apply replacement in ${fileCount} files? This will overwrite files on disk.`;
              if (!confirm(msg)) return;
              await api.post("/api/search/replace", { workspace: workspace.path, query, replacement, apply: true, regex, case_sensitive: caseSensitive, whole_word: wholeWord });
              setMatches([]);
            }}
          >
            Apply Replace
          </Button>
        </div>
      </div>
    </section>
  );
}
