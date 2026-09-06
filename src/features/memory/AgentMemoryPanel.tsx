import React, { useState, useEffect, useMemo } from "react";
import {
  Brain,
  Sparkles,
  Trash2,
  TrendingUp,
  Plus,
  Search,
  AlertTriangle,
  CheckCircle2,
  Shield,
  Clock,
  RotateCcw,
  Zap,
  Filter,
  X,
  BookOpen,
} from "lucide-react";
import { useMemoryStore, AgentMemory } from "./memoryStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";

interface CategoryMeta {
  label: string;
  icon: React.ElementType;
  badgeClass: string;
  dotClass: string;
}

const CATEGORY_META: Record<string, CategoryMeta> = {
  all: {
    label: "All Memories",
    icon: Brain,
    badgeClass: "bg-slate-800 text-slate-200 border-slate-700",
    dotClass: "bg-slate-400",
  },
  manual: {
    label: "Manual Rule",
    icon: Sparkles,
    badgeClass: "bg-cyan-950/70 text-cyan-300 border-cyan-700/50",
    dotClass: "bg-cyan-400",
  },
  user_correction: {
    label: "User Correction",
    icon: BookOpen,
    badgeClass: "bg-blue-950/70 text-blue-300 border-blue-700/50",
    dotClass: "bg-blue-400",
  },
  rejected_edit: {
    label: "Rejected Edit",
    icon: X,
    badgeClass: "bg-rose-950/70 text-rose-300 border-rose-700/50",
    dotClass: "bg-rose-400",
  },
  failed_test: {
    label: "Failed Test",
    icon: AlertTriangle,
    badgeClass: "bg-orange-950/70 text-orange-300 border-orange-700/50",
    dotClass: "bg-orange-400",
  },
  repair_loop: {
    label: "Repair Loop",
    icon: RotateCcw,
    badgeClass: "bg-amber-950/70 text-amber-300 border-amber-700/50",
    dotClass: "bg-amber-400",
  },
  security_fix: {
    label: "Security Fix",
    icon: Shield,
    badgeClass: "bg-purple-950/70 text-purple-300 border-purple-700/50",
    dotClass: "bg-purple-400",
  },
};

export const AgentMemoryPanel: React.FC = () => {
  const { currentWorkspace } = useWorkspaceStore();
  const {
    memories,
    isLoading,
    error,
    activeCategory,
    searchQuery,
    fetchMemories,
    addMemory,
    deleteMemory,
    boostMemory,
    setActiveCategory,
    setSearchQuery,
  } = useMemoryStore();

  const [newLesson, setNewLesson] = useState("");
  const [newCategory, setNewCategory] = useState("manual");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showTeachForm, setShowTeachForm] = useState(true);

  const workspacePath = typeof currentWorkspace === "string" ? currentWorkspace : (currentWorkspace?.path || "");

  // Load memories on mount and whenever workspace changes
  useEffect(() => {
    if (workspacePath) {
      fetchMemories(workspacePath);
    }
  }, [workspacePath, fetchMemories]);

  // Filter memories by category and search query
  const filteredMemories = useMemo(() => {
    return memories.filter((m) => {
      const matchCategory = activeCategory === "all" || m.category === activeCategory;
      const matchSearch =
        !searchQuery.trim() ||
        m.lesson.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (m.raw_event && m.raw_event.toLowerCase().includes(searchQuery.toLowerCase()));
      return matchCategory && matchSearch;
    });
  }, [memories, activeCategory, searchQuery]);

  // Counts by category
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { all: memories.length };
    for (const m of memories) {
      counts[m.category] = (counts[m.category] || 0) + 1;
    }
    return counts;
  }, [memories]);

  const totalApplied = useMemo(() => {
    return memories.reduce((acc, m) => acc + (m.times_applied || 0), 0);
  }, [memories]);

  const handleAddLesson = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!newLesson.trim() || !workspacePath) return;

    setIsSubmitting(true);
    try {
      await addMemory(workspacePath, newLesson.trim(), newCategory, 100);
      setNewLesson("");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      handleAddLesson();
    }
  };

  return (
    <div
      id="agent-memory-panel"
      className="flex flex-col h-full bg-slate-950 text-slate-100 overflow-hidden select-none"
    >
      {/* Header */}
      <div className="px-4 py-3.5 border-b border-slate-800 bg-slate-900/80 backdrop-blur-md flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-cyan-600 to-indigo-600 flex items-center justify-center shadow-md shadow-cyan-900/30">
            <Brain className="w-4 h-4 text-white animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-slate-100 tracking-wide">Agent Memory & Feedback</h2>
              <span className="px-1.5 py-0.5 text-[10px] font-medium bg-cyan-950 text-cyan-300 border border-cyan-800/60 rounded-full">
                Self-Improving
              </span>
            </div>
            <p className="text-[11px] text-slate-400">
              Workspace memories injected into future system prompts
            </p>
          </div>
        </div>

        <button
          id="btn-toggle-teach"
          onClick={() => setShowTeachForm(!showTeachForm)}
          className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg transition"
        >
          <Plus className="w-3.5 h-3.5 text-cyan-400" />
          <span>{showTeachForm ? "Hide Teach" : "Teach Agent"}</span>
        </button>
      </div>

      {/* Stats Summary Bar */}
      <div className="px-4 py-2 bg-slate-900/40 border-b border-slate-800/80 flex items-center gap-4 text-xs">
        <div className="flex items-center gap-1.5 text-slate-300">
          <Brain className="w-3.5 h-3.5 text-cyan-400" />
          <span className="font-semibold text-slate-100">{memories.length}</span>
          <span className="text-slate-400 text-[11px]">Memories</span>
        </div>
        <div className="h-3.5 w-px bg-slate-800" />
        <div className="flex items-center gap-1.5 text-slate-300">
          <Zap className="w-3.5 h-3.5 text-amber-400" />
          <span className="font-semibold text-slate-100">{totalApplied}</span>
          <span className="text-slate-400 text-[11px]">Times Applied</span>
        </div>
        <div className="h-3.5 w-px bg-slate-800" />
        <div className="flex items-center gap-1.5 text-slate-300">
          <Shield className="w-3.5 h-3.5 text-purple-400" />
          <span className="font-semibold text-slate-100">
            {memories.filter((m) => m.confidence >= 90).length}
          </span>
          <span className="text-slate-400 text-[11px]">High Confidence</span>
        </div>
      </div>

      {/* Teach Agent Collapsible Form */}
      {showTeachForm && (
        <div className="p-3.5 border-b border-slate-800/90 bg-gradient-to-b from-slate-900/70 to-slate-950/50">
          <form onSubmit={handleAddLesson} className="space-y-2.5">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
                <span>Teach Agent a Lesson</span>
              </label>
              <select
                id="teach-category-select"
                value={newCategory}
                onChange={(e) => setNewCategory(e.target.value)}
                className="bg-slate-900 text-xs border border-slate-700 rounded-md px-2 py-0.5 text-slate-200 focus:outline-none focus:border-cyan-500"
              >
                <option value="manual">Manual Rule</option>
                <option value="user_correction">User Correction</option>
                <option value="rejected_edit">Rejected Edit</option>
                <option value="failed_test">Failed Test</option>
                <option value="repair_loop">Repair Loop</option>
                <option value="security_fix">Security Fix</option>
              </select>
            </div>

            <div className="relative">
              <textarea
                id="teach-lesson-input"
                rows={2}
                value={newLesson}
                onChange={(e) => setNewLesson(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="e.g., Always use parameterized queries and never concatenate raw SQL strings."
                className="w-full bg-slate-900/90 border border-slate-800 focus:border-cyan-500 rounded-lg p-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none resize-none"
              />
              <div className="flex items-center justify-between mt-1 text-[10px] text-slate-400">
                <span>Tip: Guidelines start with <strong>Always</strong> or <strong>Never</strong></span>
                <span className="text-slate-500">Ctrl+Enter to save</span>
              </div>
            </div>

            <div className="flex justify-end">
              <button
                id="btn-save-lesson"
                type="submit"
                disabled={!newLesson.trim() || isSubmitting}
                className="flex items-center gap-1.5 px-3 py-1 text-xs font-medium bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 hover:to-indigo-500 disabled:opacity-50 text-white rounded-lg transition shadow-sm"
              >
                {isSubmitting ? (
                  <Clock className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <CheckCircle2 className="w-3.5 h-3.5" />
                )}
                <span>Save to Memory</span>
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Category Pills & Search */}
      <div className="px-3.5 py-2.5 border-b border-slate-800 flex flex-col gap-2 bg-slate-900/20">
        {/* Search */}
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            id="memory-search-input"
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search lessons or mistakes..."
            className="w-full bg-slate-900/80 border border-slate-800 rounded-md pl-8 pr-7 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </div>

        {/* Category Pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 no-scrollbar">
          {Object.entries(CATEGORY_META).map(([catKey, meta]) => {
            const count = categoryCounts[catKey] || 0;
            const isActive = activeCategory === catKey;
            const Icon = meta.icon;

            return (
              <button
                key={catKey}
                id={`category-pill-${catKey}`}
                onClick={() => setActiveCategory(catKey)}
                className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium transition border shrink-0 ${
                  isActive
                    ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/50"
                    : "bg-slate-900/60 text-slate-400 border-slate-800 hover:bg-slate-800/80 hover:text-slate-200"
                }`}
              >
                <Icon className="w-3 h-3" />
                <span>{meta.label}</span>
                <span
                  className={`text-[9px] px-1 rounded-full ${
                    isActive ? "bg-cyan-950 text-cyan-300" : "bg-slate-800 text-slate-400"
                  }`}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="mx-3.5 mt-2 p-2 bg-rose-950/40 border border-rose-800/60 rounded-md text-xs text-rose-300 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 text-rose-400" />
          <span>{error}</span>
        </div>
      )}

      {/* Memory List */}
      <div className="flex-1 overflow-y-auto p-3.5 space-y-2.5">
        {isLoading && memories.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-slate-500 text-xs">
            <Clock className="w-5 h-5 animate-spin mb-2 text-cyan-400" />
            <span>Loading lessons learned...</span>
          </div>
        ) : filteredMemories.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-52 text-center p-4 border border-dashed border-slate-800 rounded-xl bg-slate-900/20">
            <Brain className="w-8 h-8 text-slate-600 mb-2" />
            <h3 className="text-xs font-semibold text-slate-300 mb-1">
              {searchQuery || activeCategory !== "all"
                ? "No matching memories found"
                : "No mistakes or lessons recorded yet"}
            </h3>
            <p className="text-[11px] text-slate-500 max-w-xs mb-3">
              As you work, the agent automatically captures rejected proposals, test failures, and
              repair rounds. You can also teach it manual rules above!
            </p>
            {(!searchQuery && activeCategory === "all") && (
              <button
                id="btn-seed-sample-rule"
                onClick={() => {
                  setNewLesson("Always write unit tests for newly created backend endpoints.");
                  setNewCategory("manual");
                }}
                className="px-2.5 py-1 text-xs text-cyan-400 bg-cyan-950/60 border border-cyan-800/60 hover:bg-cyan-900/60 rounded-md transition"
              >
                + Seed sample guideline
              </button>
            )}
          </div>
        ) : (
          filteredMemories.map((mem) => {
            const meta = CATEGORY_META[mem.category] || CATEGORY_META.manual;
            const CategoryIcon = meta.icon;

            const confColor =
              mem.confidence >= 85
                ? "text-emerald-400 bg-emerald-950/60 border-emerald-800/60"
                : mem.confidence >= 60
                ? "text-amber-400 bg-amber-950/60 border-amber-800/60"
                : "text-rose-400 bg-rose-950/60 border-rose-800/60";

            return (
              <div
                key={mem.id}
                id={`memory-card-${mem.id}`}
                className="group relative bg-slate-900/60 hover:bg-slate-900/90 border border-slate-800/90 hover:border-slate-700/80 rounded-xl p-3 transition shadow-sm backdrop-blur-sm"
              >
                {/* Top Row: Category + Confidence + Applied Count */}
                <div className="flex items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border ${meta.badgeClass}`}
                    >
                      <CategoryIcon className="w-3 h-3" />
                      {meta.label}
                    </span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-semibold border ${confColor}`}
                      title={`Confidence: ${mem.confidence}%`}
                    >
                      {mem.confidence}% conf
                    </span>
                  </div>

                  <div className="flex items-center gap-1">
                    <span className="text-[10px] text-slate-400 flex items-center gap-1 bg-slate-800/60 px-1.5 py-0.5 rounded border border-slate-800">
                      <Zap className="w-2.5 h-2.5 text-amber-400" />
                      Applied {mem.times_applied}x
                    </span>
                  </div>
                </div>

                {/* Lesson Text */}
                <div className="text-xs font-medium text-slate-100 mb-2 leading-relaxed">
                  {mem.lesson}
                </div>

                {/* Optional Raw Event Snippet */}
                {mem.raw_event && mem.raw_event !== mem.lesson && (
                  <div className="text-[11px] text-slate-400 bg-slate-950/60 p-2 rounded border border-slate-800/80 mb-2 font-mono truncate">
                    <span className="text-slate-500 select-none">Trigger: </span>
                    {mem.raw_event}
                  </div>
                )}

                {/* Bottom Row: Actions */}
                <div className="flex items-center justify-between pt-1 border-t border-slate-800/60 text-[10px] text-slate-400">
                  <span>{mem.created_at ? new Date(mem.created_at).toLocaleDateString() : "Active"}</span>

                  <div className="flex items-center gap-1 opacity-80 group-hover:opacity-100 transition">
                    <button
                      id={`btn-boost-${mem.id}`}
                      onClick={() => boostMemory(mem.id, 10)}
                      title="Reinforce / Boost confidence by 10%"
                      className="flex items-center gap-1 px-2 py-0.5 bg-slate-800 hover:bg-slate-700 hover:text-emerald-300 text-slate-300 rounded border border-slate-700 transition"
                    >
                      <TrendingUp className="w-3 h-3 text-emerald-400" />
                      <span>Boost</span>
                    </button>

                    <button
                      id={`btn-forget-${mem.id}`}
                      onClick={() => deleteMemory(mem.id)}
                      title="Forget this memory"
                      className="flex items-center gap-1 px-2 py-0.5 bg-slate-800 hover:bg-rose-950/60 hover:text-rose-300 text-slate-300 rounded border border-slate-700 transition"
                    >
                      <Trash2 className="w-3 h-3 text-rose-400" />
                      <span>Forget</span>
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

export default AgentMemoryPanel;
