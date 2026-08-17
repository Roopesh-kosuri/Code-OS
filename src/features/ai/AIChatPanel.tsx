import { useEffect, useState, useCallback, useRef } from "react";
import {
  Bot,
  Copy,
  Paperclip,
  RotateCcw,
  Square,
  ChevronDown,
  ChevronUp,
  History,
  Plus,
  Trash2,
  Edit2,
  Check,
  X,
  FileDiff,
  Mic,
  MicOff,
  Send,
  Loader2,
  Eye,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { ProviderSelector, type ProviderConfig } from "../../components/ui/ProviderSelector";
import { getPreset } from "../../lib/providerPresets";
import { useAIStore, type ExtendedChatMessage, type ChatThread } from "../../stores/aiStore";
import { useEditorStore } from "../../stores/editorStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { api } from "../../lib/api";
import { AgentStatusIndicator } from "./AgentStatusIndicator";
import { DockedApprovalCard } from "./DockedApprovalCard";
import { Sparkles, Zap, CheckCircle2, XCircle, ExternalLink } from "lucide-react";

function parseProposals(text: string) {
  const proposals: { path: string; original: string; updated: string }[] = [];
  const regex = /\[PROPOSAL:\s*([^\]]+)\]\s*<<<<(?: ORIGINAL)?\r?\n([\s\S]*?)\r?\n====\r?\n([\s\S]*?)\r?\n>{3,}/g;
  let match;
  while ((match = regex.exec(text)) !== null) {
    proposals.push({
      path: match[1].trim(),
      original: match[2],
      updated: match[3],
    });
  }
  let cleanText = text.replace(
    regex,
    (m, path) => `\n*(Pending code changes proposed for \`${path}\` — inspect changes below)*\n`
  );

  // Clean raw agent control blocks (these are rendered in the AgentStatusIndicator)
  cleanText = cleanText.replace(/\[PLAN\][\s\S]*?\[\/PLAN\]/gi, "");
  cleanText = cleanText.replace(/\[TOOL_CALL:[^\]]+\][\s\S]*?\[\/TOOL_CALL\]/gi, "");
  cleanText = cleanText.replace(/\[TOOL_RESULT:[^\]]+\][\s\S]*?\[\/TOOL_RESULT\]/gi, "");
  cleanText = cleanText.replace(/\[DONE\]/gi, "");
  cleanText = cleanText.replace(/\[ESCALATE\]/gi, "");
  cleanText = cleanText.trim();

  return { cleanText, proposals };
}

function ChatCodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    void navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="bg-[#0a0a0c] border border-surface-variant rounded-lg overflow-hidden my-2.5 select-text font-mono text-xs shadow-inner w-full min-w-0 max-w-full">
      <div className="bg-surface-container-high px-3 py-1.5 flex justify-between items-center border-b border-surface-variant select-none">
        <span className="font-caption text-caption text-on-surface-variant uppercase text-[10px] font-bold">{language || "code"}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="text-on-surface-variant hover:text-primary transition-colors flex items-center gap-1 text-[11px] cursor-pointer"
        >
          {copied ? <><Check size={12} /> Copied</> : <><Copy size={12} /> Copy</>}
        </button>
      </div>
      <pre className="p-3 overflow-x-auto w-full min-w-0 max-w-full leading-relaxed text-on-surface font-code-sm text-code-sm">
        <code className="break-normal whitespace-pre block">{code}</code>
      </pre>
    </div>
  );
}

function ProposalCard({ path, original, updated }: { path: string; original: string; updated: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    void navigator.clipboard.writeText(updated);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleOpenDiff = () => {
    window.dispatchEvent(new CustomEvent("code-os:switch-top-view", { detail: "proposals" }));
  };

  return (
    <div className="mt-3 rounded-xl border border-primary-container/30 bg-primary-container/5 p-4 space-y-3 text-xs shadow-md">
      <div className="flex items-center justify-between border-b border-surface-variant pb-2">
        <div className="flex items-center gap-2 font-ui-label-bold text-ui-label-bold text-on-surface truncate">
          <FileDiff size={14} className="text-primary-container shrink-0" />
          <span className="truncate">{path.split(/[\\/]/).pop() ?? path}</span>
        </div>
        <span className="rounded-full bg-primary-container/10 border border-primary-container/20 px-2 py-0.5 text-[9px] text-primary font-bold uppercase shrink-0">
          PROPOSAL
        </span>
      </div>

      <div className="flex justify-between items-center gap-2 pt-1">
        <button
          onClick={handleOpenDiff}
          className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-primary-container text-[#001f24] font-bold text-[11px] hover:bg-primary-fixed transition-colors shadow-sm cursor-pointer"
        >
          <Eye size={12} /> Open Diff Inspector
        </button>
        <button
          onClick={handleCopy}
          className="text-on-surface-variant hover:text-on-surface text-[11px] transition-colors cursor-pointer"
        >
          {copied ? "Copied!" : "Copy code"}
        </button>
      </div>
    </div>
  );
}

export function AIChatPanel() {
  const [prompt, setPrompt] = useState("");
  const [attachedPaths, setAttachedPaths] = useState<string[]>([]);
  const [showProviderConfig, setShowProviderConfig] = useState(false);
  const [configuredKeys, setConfiguredKeys] = useState<string[]>([]);
  const [showDrawer, setShowDrawer] = useState(false);
  const [isListening, setIsListening] = useState(false);

  const messages = useAIStore((s) => s.messages);
  const models = useAIStore((s) => s.models);
  const model = useAIStore((s) => s.model);
  const preset = useAIStore((s) => s.preset);
  const baseUrl = useAIStore((s) => s.baseUrl);
  const streaming = useAIStore((s) => s.streaming);
  const error = useAIStore((s) => s.error);
  const threads = useAIStore((s) => s.threads);
  const currentThreadId = useAIStore((s) => s.currentThreadId);

  // Agent mode state
  const agentMode = useAIStore((s) => s.agentMode);
  const agentStatus = useAIStore((s) => s.agentStatus);
  const agentPlan = useAIStore((s) => s.agentPlan);
  const agentToolHistory = useAIStore((s) => s.agentToolHistory);
  const pendingApproval = useAIStore((s) => s.pendingApproval);
  const pendingApprovals = useAIStore((s) => s.pendingApprovals);
  const pendingUserResponse = useAIStore((s) => s.pendingUserResponse);
  const respondToUserQuestion = useAIStore((s) => s.respondToUserQuestion);
  const toggleAgentMode = useAIStore((s) => s.toggleAgentMode);
  const setAgentMode = useAIStore((s) => s.setAgentMode);
  const approveAction = useAIStore((s) => s.approveAction);
  const rejectAction = useAIStore((s) => s.rejectAction);

  const sendMessage = useAIStore((s) => s.sendMessage);
  const stopGeneration = useAIStore((s) => s.stopGeneration);
  const regenerate = useAIStore((s) => s.regenerate);
  const newThread = useAIStore((s) => s.newThread);
  const switchThread = useAIStore((s) => s.switchThread);
  const setPreset = useAIStore((s) => s.setPreset);
  const setModel = useAIStore((s) => s.setModel);

  const workspace = useWorkspaceStore((s) => s.currentWorkspace);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    void api.get<{ provider_id: string; configured: boolean }[]>("/api/settings/api-keys")
      .then((k) => setConfiguredKeys(k.filter((x) => x.configured).map((x) => x.provider_id)))
      .catch(() => undefined);
  }, []);

  const providerValue: ProviderConfig = {
    preset,
    model,
    base_url: baseUrl,
  };

  const handleProviderChange = (cfg: ProviderConfig) => {
    if (cfg.preset !== preset || cfg.base_url !== baseUrl) {
      setPreset(cfg.preset, cfg.base_url, cfg.model);
    } else if (cfg.model !== model) {
      setModel(cfg.model);
    }
  };

  return (
    <section data-testid="ai-chat-panel" className="flex flex-col h-full min-h-0 w-full min-w-0 overflow-hidden bg-surface-container-low text-on-surface font-ui-label-reg text-ui-label-reg relative select-none antialiased">
      {/* ── Header / Model Selector (Elevated z-index for dropdown layering) ───────── */}
      <div className="p-4 border-b border-surface-variant flex flex-col gap-3 bg-surface-container/50 shrink-0 relative z-40">
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-2 font-ui-label-bold text-ui-label-bold text-on-surface">
            <span className="material-symbols-outlined text-primary text-xl">smart_toy</span>
            <span>Rony Agent</span>
          </div>

          <div className="flex items-center gap-2">
            {/* Mode Switch: Chat vs Agent with Fluid Sliding Thumb */}
            <div className="relative flex items-center p-0.5 rounded-lg bg-[#141519] border border-white/10 shadow-inner select-none">
              {/* Sliding Thumb */}
              <div
                className="absolute top-0.5 bottom-0.5 rounded-md transition-all duration-200"
                style={{
                  left: agentMode ? "calc(50% + 1px)" : "2px",
                  right: agentMode ? "2px" : "calc(50% + 1px)",
                  backgroundColor: agentMode ? "var(--primary, #00daf3)" : "rgba(255, 255, 255, 0.12)",
                  boxShadow: agentMode ? "0 0 12px rgba(0, 218, 243, 0.35)" : "none",
                  transitionTimingFunction: "cubic-bezier(0.16, 1, 0.3, 1)",
                }}
              />
              <button
                type="button"
                onClick={() => setAgentMode(false)}
                className={`relative z-10 px-3 py-1 rounded-md text-[11px] font-medium transition-colors cursor-pointer flex items-center justify-center gap-1 ${
                  !agentMode ? "text-on-surface font-bold" : "text-on-surface-variant/70 hover:text-on-surface"
                }`}
                title="Chat Mode: For coding doubts, questions, explanations, and quick advice"
              >
                <span>Chat</span>
              </button>
              <button
                type="button"
                onClick={() => setAgentMode(true)}
                className={`relative z-10 px-3 py-1 rounded-md text-[11px] font-medium transition-colors cursor-pointer flex items-center justify-center gap-1 ${
                  agentMode ? "text-[#001f24] font-bold" : "text-on-surface-variant/70 hover:text-on-surface"
                }`}
                title="Agent Mode: Rony Agent autonomously reads/edits files, runs terminal commands, runs tests, and verifies results"
              >
                <Sparkles size={11} className={agentMode ? "text-[#001f24]" : "text-primary"} />
                <span>Agent</span>
              </button>
            </div>

            <div className="flex items-center gap-1 text-on-surface-variant">
              <button
                onClick={() => void newThread()}
                className="p-1 hover:text-on-surface hover:bg-surface-variant rounded transition-colors cursor-pointer"
                title="New Chat"
              >
                <Plus size={16} />
              </button>
              <button
                onClick={() => setShowDrawer((v) => !v)}
                className="p-1 hover:text-on-surface hover:bg-surface-variant rounded transition-colors cursor-pointer"
                title="Chat History"
              >
                <History size={16} />
              </button>
              <button
                onClick={() => setShowProviderConfig((v) => !v)}
                className="p-1 hover:text-on-surface hover:bg-surface-variant rounded transition-colors cursor-pointer"
                title="Configure Model"
              >
                {showProviderConfig ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
            </div>
          </div>
        </div>

        {/* Model Selector Button */}
        {!showProviderConfig ? (
          <button
            onClick={() => setShowProviderConfig(true)}
            className="w-full bg-[#16181f]/80 hover:bg-[#1c1e28] border border-white/10 hover:border-primary/40 rounded-xl px-3.5 py-2 flex items-center justify-between transition-all duration-200 cursor-pointer shadow-sm group"
          >
            <div className="flex items-center gap-2.5 min-w-0 flex-1">
              <div className="w-5 h-5 rounded-lg bg-primary/20 border border-primary/30 flex items-center justify-center overflow-hidden shrink-0 text-primary group-hover:scale-105 transition-transform">
                <Sparkles size={12} />
              </div>
              <div className="flex items-center gap-2 truncate">
                <span className="font-bold text-xs text-on-surface truncate">
                  {preset ? getPreset(preset)?.label : "Auto Routing"}
                </span>
                <span className="text-[10px] text-on-surface-variant font-mono truncate max-w-[140px]">
                  {model ? model : "auto-select"}
                </span>
              </div>
            </div>
            <div className="w-5 h-5 rounded-md bg-white/5 flex items-center justify-center text-on-surface-variant group-hover:text-primary transition-colors">
              <ChevronDown size={13} />
            </div>
          </button>
        ) : (
          <div className="relative z-50 animate-popover-in">
            <ProviderSelector
              value={providerValue}
              onChange={handleProviderChange}
              configuredKeys={configuredKeys}
              models={models}
              onClose={() => setShowProviderConfig(false)}
              compact
            />
          </div>
        )}
      </div>

      {/* ── Thread History Drawer ──────────────────────────────────────────── */}
      {showDrawer && (
        <div className="absolute inset-0 bg-[#131315]/95 z-30 flex flex-col p-4 space-y-3">
          <div className="flex justify-between items-center border-b border-surface-variant pb-2">
            <span className="font-ui-label-bold text-ui-label-bold text-on-surface uppercase text-xs">Conversations</span>
            <button onClick={() => setShowDrawer(false)} className="text-on-surface-variant hover:text-on-surface">
              <X size={16} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto space-y-1.5">
            {threads.map((t) => (
              <button
                key={t.id}
                onClick={async () => {
                  await switchThread(t.id);
                  setShowDrawer(false);
                }}
                className={`w-full text-left p-2.5 rounded-xl border text-xs transition-all cursor-pointer ${
                  currentThreadId === t.id
                    ? "bg-surface-container-high border-primary/40 text-primary font-bold shadow-sm"
                    : "bg-surface-container border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high"
                }`}
              >
                <div className="truncate">{t.title}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Chat Messages Stream ───────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden p-3.5 flex flex-col gap-4 select-text min-w-0 w-full max-w-full">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center my-auto p-6 text-center text-xs text-on-surface-variant/50 space-y-2 select-none">
            <span className="material-symbols-outlined text-3xl text-outline-variant">auto_awesome</span>
            <p>Ask Rony Agent to code, explain functions, or draft autonomous changes.</p>
          </div>
        ) : null}

        {error && (
          <div className="rounded-xl border border-error/40 bg-error/10 p-3 text-xs text-error">
            {error}
          </div>
        )}

        {messages.map((message, index) => {
          const isUser = message.role === "user";
          const { cleanText, proposals } = parseProposals(message.content);
          const isStreamingMessage = streaming && !isUser && index === messages.length - 1;

          return isUser ? (
            /* User Message Bubble */
            <div key={index} className="flex flex-col gap-1 items-end animate-message-in">
              <div className="bg-surface-variant text-on-surface px-3.5 py-2 rounded-2xl rounded-tr-sm max-w-[88%] font-ui-label-reg text-ui-label-reg text-xs leading-relaxed shadow-sm break-words [overflow-wrap:anywhere] overflow-hidden">
                {cleanText}
              </div>
            </div>
          ) : (
            /* AI Response Card (Stitch Elevation 2 Card) */
            <div key={index} className="flex flex-col gap-2 items-start w-full animate-message-in">
              <div className="flex items-center gap-2 px-1">
                <span className="material-symbols-outlined text-primary text-[18px]">smart_toy</span>
                <span className="font-caption text-caption text-on-surface-variant">
                  {message.agentStatus || agentMode ? "Rony Agent" : "Rony"}
                </span>
              </div>

              <div className="bg-[#1e1f24] text-on-surface p-3.5 rounded-xl shadow-[0_4px_20px_rgba(0,0,0,0.15)] ring-1 ring-white/5 w-full min-w-0 max-w-full space-y-2.5 overflow-hidden transition-all duration-200">
                {/* Agent Status & Thinking Indicator */}
                {(message.agentStatus || message.agentPlan || (index === messages.length - 1 && (agentStatus || agentPlan || agentToolHistory.length > 0))) && (
                  <AgentStatusIndicator
                    status={message.agentStatus || (index === messages.length - 1 ? agentStatus : null)}
                    plan={message.agentPlan || (index === messages.length - 1 ? agentPlan : null)}
                    toolHistory={
                      (message.agentToolHistory && message.agentToolHistory.length > 0)
                        ? message.agentToolHistory
                        : (message.commands && message.commands.length > 0)
                          ? message.commands.map(c => ({
                              tool: "run_command",
                              detail: c.command,
                              timestamp: message.created_at || new Date().toISOString(),
                              success: c.success,
                            }))
                          : (index === messages.length - 1 ? agentToolHistory : [])
                    }
                    streaming={streaming && index === messages.length - 1}
                  />
                )}

                {cleanText ? (
                  <div className="markdown-body font-ui-label-reg text-ui-label-reg text-xs leading-relaxed break-words [overflow-wrap:anywhere] min-w-0 max-w-full overflow-hidden">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        code({ className, children }) {
                          const match = /language-(\w+)/.exec(className || "");
                          const code = String(children).replace(/\n$/, "");
                          if (match) {
                            return <ChatCodeBlock language={match[1]} code={code} />;
                          }
                          return (
                            <code className="bg-[#0a0a0c] text-primary px-1.5 py-0.5 rounded font-mono text-[11px] border border-white/5 break-words [overflow-wrap:anywhere]">
                              {children}
                            </code>
                          );
                        },
                      }}
                    >
                      {cleanText}
                    </ReactMarkdown>
                    {isStreamingMessage && <span className="streaming-caret" />}
                  </div>
                ) : isStreamingMessage ? (
                  <div className="text-xs text-primary/70 flex items-center gap-1.5 py-1">
                    <Loader2 size={13} className="animate-spin text-primary" />
                    <span className="shimmer-text">Generating response...</span>
                  </div>
                ) : null}

                {/* Live Terminal / Command & Edit Receipts Feed */}
                {message.commands && message.commands.length > 0 && (
                  <div className="space-y-2 pt-1">
                    {message.commands.map((cmd, cIdx) => {
                      const isEdit = cmd.command.startsWith("edit ") || cmd.command.startsWith("edit_file ");
                      const filePath = isEdit ? cmd.command.replace(/^edit(?:_file)?\s+/, "").trim() : "";

                      if (isEdit) {
                        return (
                          <div
                            key={cIdx}
                            className={`flex items-center justify-between px-3 py-2 rounded-lg border text-xs font-mono shadow-sm transition-all animate-success-pop ${
                              cmd.success
                                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                                : "bg-rose-500/10 border-rose-500/30 text-rose-300"
                            }`}
                          >
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                              {cmd.success ? (
                                <CheckCircle2 size={15} className="text-emerald-400 shrink-0" />
                              ) : (
                                <XCircle size={15} className="text-rose-400 shrink-0" />
                              )}
                              <span className="font-semibold text-[11.5px] truncate">
                                {cmd.success ? "✓ Approved edit to" : "✗ Denied edit to"}{" "}
                                <span className="underline decoration-dotted text-white font-mono">{filePath}</span>
                              </span>
                            </div>
                            {cmd.success && (
                              <button
                                type="button"
                                onClick={() =>
                                  window.dispatchEvent(
                                    new CustomEvent("code-os:switch-top-view", { detail: "proposals" })
                                  )
                                }
                                className="text-[10.5px] text-primary hover:underline flex items-center gap-1 cursor-pointer shrink-0 ml-2 font-sans font-medium interactive-scale"
                              >
                                <ExternalLink size={11} /> Diff
                              </button>
                            )}
                          </div>
                        );
                      }

                      // Check for denied / timed out terminal commands
                      const isRejected =
                        !cmd.success &&
                        (cmd.output?.includes("rejected by user") ||
                          cmd.output?.includes("timed out") ||
                          cmd.output?.includes("User rejected"));

                      if (isRejected) {
                        return (
                          <div
                            key={cIdx}
                            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 font-mono text-xs shadow-sm"
                          >
                            <XCircle size={14} className="text-rose-400 shrink-0" />
                            <span className="font-semibold text-[11px] truncate">
                              ✗ Denied: <span className="text-rose-200">{cmd.command}</span>
                            </span>
                          </div>
                        );
                      }

                      // Regular terminal execution output card
                      return (
                        <div
                          key={cIdx}
                          className="rounded-lg bg-[#0d0e11] border border-white/10 overflow-hidden font-mono text-xs shadow-inner"
                        >
                          <div className="flex items-center justify-between px-3 py-1.5 bg-[#16171b] border-b border-white/5 text-[11px]">
                            <div className="flex items-center gap-2 min-w-0 flex-1 truncate">
                              <span className="text-amber-400 font-bold">$</span>
                              <span className="text-on-surface truncate font-semibold">{cmd.command}</span>
                            </div>
                            <span
                              className={`px-1.5 py-0.5 rounded text-[9.5px] font-bold shrink-0 ml-2 ${
                                cmd.success
                                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                                  : "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                              }`}
                            >
                              exit: {cmd.exit_code}
                            </span>
                          </div>
                          <div className="p-2.5 text-[11px] text-[#c9d1d9] leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap select-text bg-black/50">
                            {cmd.output || "(no output)"}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Proposals Card */}
                {proposals.map((p, pIdx) => (
                  <ProposalCard key={pIdx} path={p.path} original={p.original} updated={p.updated} />
                ))}
              </div>
            </div>
          );
        })}

        {streaming && !agentMode && (
          <div className="flex items-center gap-2 text-primary text-xs px-2 animate-pulse">
            <Loader2 size={14} className="animate-spin" />
            <span>Thinking…</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* ── Docked Approval Card (Pinned Directly Above Chat Input) ───────── */}
      {pendingApproval && (
        <DockedApprovalCard
          pendingApproval={pendingApproval}
          pendingApprovals={pendingApprovals}
          onApprove={approveAction}
          onReject={rejectAction}
        />
      )}

      {/* ── Interactive Clarification Card (ask_user) ──────────────────────── */}
      {pendingUserResponse && (
        <div className="border-t border-b px-4 py-3 shrink-0 bg-[#12141a]/95 border-primary/40 shadow-lg z-20 animate-docked-in backdrop-blur-xl">
          <div className="flex items-center gap-2 mb-2">
            <div className="p-1 rounded-md bg-primary/20 text-primary">
              <Bot size={14} />
            </div>
            <span className="font-bold text-xs text-primary">Clarification Requested</span>
          </div>
          <p className="text-xs text-on-surface mb-2.5 leading-relaxed">{pendingUserResponse.question}</p>
          <div className="flex flex-wrap gap-1.5">
            {pendingUserResponse.options.map((opt, oIdx) => (
              <button
                key={oIdx}
                type="button"
                onClick={() => {
                  void respondToUserQuestion(pendingUserResponse.action_id, opt);
                  void sendMessage(opt, attachedPaths);
                }}
                className="px-3 py-1.5 rounded-full bg-primary/15 hover:bg-primary/25 text-primary border border-primary/30 text-xs font-medium cursor-pointer transition-all hover:scale-[1.02] active:scale-[0.98]"
              >
                {opt}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Chat Input Container (Google Stitch Footer) ───────────────────── */}
      <div className="p-4 border-t border-surface-variant bg-surface-container/80 backdrop-blur-md shrink-0">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!prompt.trim() || streaming) return;
            const text = prompt;
            setPrompt("");
            void sendMessage(text, attachedPaths);
            setAttachedPaths([]);
          }}
          className="bg-[#1e1f24] rounded-xl p-1 border border-transparent focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/20 transition-all duration-200 shadow-lg"
        >
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (prompt.trim() && !streaming) {
                  const text = prompt;
                  setPrompt("");
                  void sendMessage(text, attachedPaths);
                  setAttachedPaths([]);
                }
              }
            }}
            placeholder={
              agentMode
                ? "Describe the coding task for Rony Agent… (@ to mention files)"
                : "Ask a coding question… (@ to mention files)"
            }
            rows={2}
            className="w-full bg-transparent border-none focus:ring-0 text-on-surface font-ui-label-reg text-ui-label-reg placeholder:text-outline-variant resize-none p-3 outline-none text-xs"
          />

          <div className="flex justify-between items-center px-2 pb-2">
            <div className="flex gap-1 text-on-surface-variant">
              <button
                type="button"
                className="p-1.5 hover:text-primary hover:bg-primary/10 rounded-lg transition-colors cursor-pointer interactive-scale"
                title="Attach context file"
              >
                <Paperclip size={16} />
              </button>
              <button
                type="button"
                onClick={() => setIsListening(!isListening)}
                className={`p-1.5 rounded-lg transition-colors cursor-pointer interactive-scale ${
                  isListening ? "text-error bg-error/10 animate-pulse" : "hover:text-primary hover:bg-primary/10"
                }`}
                title="Voice input"
              >
                {isListening ? <MicOff size={16} /> : <Mic size={16} />}
              </button>
            </div>

            {streaming ? (
              <button
                type="button"
                onClick={stopGeneration}
                className="bg-error text-on-error w-8 h-8 rounded-full flex items-center justify-center hover:bg-error-container transition-all cursor-pointer shadow-md interactive-scale"
                title="Stop generation"
              >
                <Square size={14} />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!prompt.trim()}
                className="bg-primary-container text-on-primary-container w-8 h-8 rounded-full flex items-center justify-center hover:bg-primary transition-all disabled:opacity-40 cursor-pointer shadow-md interactive-scale"
                title="Send Message"
              >
                <span className="material-symbols-outlined text-[18px]">arrow_upward</span>
              </button>
            )}
          </div>
        </form>

        <div className="text-center mt-2">
          <span className="font-caption text-[10px] text-outline-variant">AI generated code may contain errors.</span>
        </div>
      </div>
    </section>
  );
}
