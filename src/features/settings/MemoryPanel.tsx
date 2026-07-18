import { useEffect, useState } from "react";
import { Brain, Trash2, Save, Sparkles } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { api } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";

export function MemoryPanel() {
  const [memory, setMemory] = useState<Record<string, string>>({});
  const [styleGuide, setStyleGuide] = useState("");
  const [preferences, setPreferences] = useState("");
  const [recentFixes, setRecentFixes] = useState("");
  const [currentTasks, setCurrentTasks] = useState("");
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);

  const fetchMemory = async () => {
    if (!workspace) return;
    try {
      const data = await api.get<Record<string, string>>("/api/settings/memory", { workspace: workspace.path });
      setMemory(data);
      setStyleGuide(data.styleGuide || "");
      setPreferences(data.preferences || "");
      setRecentFixes(data.recentFixes || "");
      setCurrentTasks(data.currentTasks || "");
    } catch {
      setMemory({});
    }
  };

  useEffect(() => {
    void fetchMemory();
  }, [workspace?.path]);

  const handleSave = async (key: string, value: string) => {
    if (!workspace) return;
    try {
      await api.post("/api/settings/memory", {
        workspace: workspace.path,
        key,
        value
      });
      await fetchMemory();
    } catch (err) {
      alert("Failed to save memory: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleClear = async () => {
    if (!workspace || !confirm("Clear all project conversation memory?")) return;
    try {
      await api.delete("/api/settings/memory", { workspace: workspace.path });
      setMemory({});
      setStyleGuide("");
      setPreferences("");
      setRecentFixes("");
      setCurrentTasks("");
    } catch (err) {
      alert("Failed to clear memory: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  if (!workspace) {
    return <div className="p-3 text-sm text-slate-500">Open a workspace to view project memory settings.</div>;
  }

  return (
    <section className="grid h-full min-h-0 w-full min-w-0 grid-cols-1 grid-rows-[38px_1fr] border-b border-surface-700">
      <div className="flex items-center justify-between border-b border-surface-700 px-3 py-1">
        <div className="flex items-center gap-2">
          <Brain size={15} className="text-slate-400" />
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Project AI Memory</span>
        </div>
        <button onClick={() => void handleClear()} className="text-slate-500 hover:text-rose-400" title="Clear memory">
          <Trash2 size={14} />
        </button>
      </div>

      <div className="overflow-auto p-3 text-xs space-y-4 min-h-0">
        <p className="text-[10px] text-slate-500 italic">
          This memory persists local context about coding style, tasks, and preferences to automatically improve AI interactions.
        </p>

        {/* Coding Style */}
        <div className="space-y-1">
          <div className="flex justify-between items-center">
            <span className="font-semibold text-slate-300">Coding Style Rules</span>
            <button onClick={() => void handleSave("styleGuide", styleGuide)} className="text-[10px] text-accent-400 hover:text-accent-300 flex items-center gap-0.5">
              <Save size={10} /> Save
            </button>
          </div>
          <textarea
            className="w-full h-16 rounded border-surface-700 bg-surface-850 text-slate-200 text-xs p-1.5 font-mono resize-none focus:outline-none focus:border-accent-500"
            value={styleGuide}
            onChange={(e) => setStyleGuide(e.target.value)}
            placeholder="e.g. Use async/await, no semicolons, write unit tests..."
          />
        </div>

        {/* User Preferences */}
        <div className="space-y-1">
          <div className="flex justify-between items-center">
            <span className="font-semibold text-slate-300">User Preferences</span>
            <button onClick={() => void handleSave("preferences", preferences)} className="text-[10px] text-accent-400 hover:text-accent-300 flex items-center gap-0.5">
              <Save size={10} /> Save
            </button>
          </div>
          <textarea
            className="w-full h-16 rounded border-surface-700 bg-surface-850 text-slate-200 text-xs p-1.5 font-mono resize-none focus:outline-none focus:border-accent-500"
            value={preferences}
            onChange={(e) => setPreferences(e.target.value)}
            placeholder="e.g. Prefer typescript files, prefer clean OOP style..."
          />
        </div>

        {/* Current Tasks */}
        <div className="space-y-1">
          <div className="flex justify-between items-center">
            <span className="font-semibold text-slate-300">Current AI Checklist / Tasks</span>
            <button onClick={() => void handleSave("currentTasks", currentTasks)} className="text-[10px] text-accent-400 hover:text-accent-300 flex items-center gap-0.5">
              <Save size={10} /> Save
            </button>
          </div>
          <textarea
            className="w-full h-16 rounded border-surface-700 bg-surface-850 text-slate-200 text-xs p-1.5 font-mono resize-none focus:outline-none focus:border-accent-500"
            value={currentTasks}
            onChange={(e) => setCurrentTasks(e.target.value)}
            placeholder="e.g. Implement index router, debug auth logic..."
          />
        </div>
      </div>
    </section>
  );
}
