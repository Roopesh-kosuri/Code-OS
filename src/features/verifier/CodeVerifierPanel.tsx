import { useState, useEffect } from "react";
import {
  Shield,
  ShieldAlert,
  ShieldCheck,
  Play,
  RotateCcw,
  CheckCircle2,
  AlertTriangle,
  FileCode,
  Lock,
  ExternalLink,
  ChevronDown,
  Info,
  Download,
  FileText,
  Check,
  X,
  Loader2,
  Sparkles,
} from "lucide-react";
import { ProviderSelector, type ProviderConfig } from "../../components/ui/ProviderSelector";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { useAIStore } from "../../stores/aiStore";
import { api } from "../../lib/api";

interface AuditFinding {
  id: string;
  rule_id?: string;
  cwe_id?: string;
  severity: "critical" | "high" | "medium" | "low" | "info" | string;
  file: string;
  line: number;
  message?: string;
  title?: string;
  snippet?: string;
  code_snippet?: string;
  remediation?: string;
  fix_suggestion?: string;
  description?: string;
}

interface AuditReport {
  id?: string;
  workspace?: string;
  timestamp: string;
  total_files_scanned?: number;
  duration_seconds?: number;
  findings: AuditFinding[];
  score: number; // 0 - 100
  summary?: string;
  severity_counts?: {
    critical: number;
    high: number;
    medium: number;
    low: number;
  };
}

export function CodeVerifierPanel() {
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);
  const globalModel = useAIStore((state) => state.model);
  const globalPreset = useAIStore((state) => state.preset);
  const models = useAIStore((state) => state.models);

  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<AuditReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedSeverity, setSelectedSeverity] = useState<string>("all");
  const [selectedFinding, setSelectedFinding] = useState<AuditFinding | null>(null);
  const [showConfig, setShowConfig] = useState(false);

  const [providerConfig, setProviderConfig] = useState<ProviderConfig>({
    preset: globalPreset || "ollama",
    model: globalModel || "llama3",
  });

  // Save Modal
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [savingFile, setSavingFile] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);

  const runAudit = async () => {
    if (!workspace) return;
    setRunning(true);
    setError(null);

    try {
      const res = await api.post<AuditReport>("/api/agents/audit", {
        workspace: workspace.path,
        provider_config: {
          preset: providerConfig.preset,
          model: providerConfig.model,
          base_url: providerConfig.base_url,
        },
      });

      if (res) {
        setReport(res);
        if (res.findings && res.findings.length > 0) {
          setSelectedFinding(res.findings[0]);
        }
      }
    } catch (err: any) {
      setError(err?.message || "Failed to execute security audit scan.");
    } finally {
      setRunning(false);
    }
  };

  const generateMarkdownReport = (): string => {
    if (!report) return "";
    const lines = [
      `# Security Audit Report — ${workspace?.name ?? "Workspace"}`,
      `Date: ${new Date(report.timestamp).toLocaleString()}`,
      `Security Score: ${report.score}/100`,
      `Total Findings: ${report.findings?.length ?? 0}`,
      "",
      "## Severity Breakdown",
      `- Critical: ${counts.critical}`,
      `- High: ${counts.high}`,
      `- Medium: ${counts.medium}`,
      `- Low: ${counts.low}`,
      "",
      "## Findings & Remediation",
      "",
    ];

    (report.findings || []).forEach((f, idx) => {
      lines.push(`### ${idx + 1}. [${f.severity.toUpperCase()}] ${f.title || f.message || "Security Issue"}`);
      lines.push(`**Location**: \`${f.file}:${f.line}\``);
      if (f.cwe_id || f.rule_id) lines.push(`**Rule/CWE**: ${f.cwe_id || f.rule_id}`);
      if (f.description) lines.push(`\n${f.description}`);
      if (f.code_snippet || f.snippet) {
        lines.push(`\n\`\`\`\n${f.code_snippet || f.snippet}\n\`\`\``);
      }
      if (f.fix_suggestion || f.remediation) {
        lines.push(`\n**Recommended Fix**: ${f.fix_suggestion || f.remediation}`);
      }
      lines.push("\n---");
    });

    return lines.join("\n");
  };

  const handleDownloadMarkdown = () => {
    const md = generateMarkdownReport();
    if (!md) return;
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `SECURITY_AUDIT_${workspace?.name || "workspace"}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleSaveToWorkspace = async () => {
    if (!workspace || !report) return;
    setSavingFile(true);
    try {
      const md = generateMarkdownReport();
      await api.post("/api/agents/audit/save-report", {
        workspace: workspace.path,
        markdown_content: md,
      });
      setSavedSuccess(true);
      void useWorkspaceStore.getState().refreshTree();
      setTimeout(() => {
        setShowSaveModal(false);
        setSavedSuccess(false);
      }, 1500);
    } catch (err: any) {
      setError(err?.message || "Failed to save audit report to workspace");
    } finally {
      setSavingFile(false);
    }
  };

  const findings = report?.findings || [];
  const filteredFindings = findings.filter(
    (f) => selectedSeverity === "all" || f.severity.toLowerCase() === selectedSeverity.toLowerCase()
  );

  const counts = {
    critical: report?.severity_counts?.critical ?? findings.filter((f) => f.severity.toLowerCase() === "critical").length,
    high: report?.severity_counts?.high ?? findings.filter((f) => f.severity.toLowerCase() === "high").length,
    medium: report?.severity_counts?.medium ?? findings.filter((f) => f.severity.toLowerCase() === "medium").length,
    low: report?.severity_counts?.low ?? findings.filter((f) => f.severity.toLowerCase() === "low").length,
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-background text-on-surface font-ui-label-reg text-ui-label-reg antialiased select-none">
      {/* ── Contextual Verifier Header ──────────────────────────────────────── */}
      <div className="level-1-panel px-6 py-4 flex justify-between items-center border-b border-surface-variant/50 shrink-0">
        <div className="flex items-center gap-4">
          <div className="bg-primary-container/10 p-2 rounded-lg text-primary">
            <span className="material-symbols-outlined text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>
              shield
            </span>
          </div>
          <div>
            <h1 className="font-headline-md text-headline-md text-on-surface font-bold">
              Code Verification Agent
            </h1>
            <p className="font-caption text-caption text-on-surface-variant mt-0.5">
              Multi-pass SAST security audit for SQL injection, exposed credentials, and logic flaws.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          {/* Model Selector Dropdown */}
          <div className="relative">
            <button
              onClick={() => setShowConfig(!showConfig)}
              className="level-2-panel rounded-full px-4 py-2 flex items-center gap-2 cursor-pointer hover:bg-surface-variant transition-colors border border-outline-variant/30 glow-accent text-xs"
            >
              <span className="material-symbols-outlined text-[16px] text-primary">smart_toy</span>
              <span className="font-ui-label-bold text-ui-label-bold text-on-surface">{providerConfig.model}</span>
              <ChevronDown size={14} className="text-on-surface-variant ml-1" />
            </button>

            {showConfig && (
              <div className="absolute right-0 top-12 z-50 w-72 bg-[#1e1f24] border border-surface-container-high rounded-xl p-3 shadow-2xl">
                <ProviderSelector
                  value={providerConfig}
                  onChange={(cfg) => {
                    setProviderConfig(cfg);
                    setShowConfig(false);
                  }}
                  models={models}
                  compact
                />
              </div>
            )}
          </div>

          {/* Status Badge */}
          <div className="bg-primary/10 text-primary px-3 py-1 rounded-full font-caption text-caption flex items-center gap-2 border border-primary/20">
            <div className={`w-1.5 h-1.5 rounded-full bg-primary ${running ? "animate-spin" : "animate-pulse"}`} />
            <span>{running ? "AUDITING WORKSPACE..." : report ? "AUDIT COMPLETED" : "READY"}</span>
          </div>
        </div>
      </div>

      {error && (
        <div className="m-6 mb-0 rounded-xl border border-error/40 bg-error/10 p-4 text-xs text-error flex items-center justify-between shadow-lg">
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} />
            <span>{error}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => void runAudit()}
              className="px-3 py-1 bg-error text-on-error font-bold rounded-full hover:bg-error-container transition-colors cursor-pointer"
            >
              Retry
            </button>
            <button onClick={() => setError(null)} className="text-error hover:opacity-80">
              <X size={14} />
            </button>
          </div>
        </div>
      )}

      {/* ── Main Canvas View (Empty State, Loading, or Report) ──────────────── */}
      {running ? (
        <main className="flex-1 flex flex-col items-center justify-center p-8 space-y-4">
          <div className="w-16 h-16 rounded-full bg-primary-container/10 border border-primary-container/30 flex items-center justify-center text-primary-container animate-pulse shadow-[0_0_30px_rgba(0,218,243,0.3)]">
            <Loader2 size={32} className="animate-spin" />
          </div>
          <div className="text-center space-y-1">
            <h3 className="font-headline-md text-headline-md text-on-surface font-bold">Scanning Codebase Files...</h3>
            <p className="text-xs text-on-surface-variant font-mono">Running AST and SAST heuristic security rules via {providerConfig.model}</p>
          </div>
        </main>
      ) : !report ? (
        <main className="flex-1 bg-background overflow-y-auto flex flex-col items-center justify-center p-6 relative empty-state-shield-container">
          {/* Decorative Radial Grid */}
          <div className="absolute inset-0 pointer-events-none overflow-hidden">
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-primary/5 rounded-full blur-[100px] opacity-30" />
            <div
              className="absolute inset-0"
              style={{
                backgroundImage: "radial-gradient(#353437 1px, transparent 1px)",
                backgroundSize: "24px 24px",
                opacity: 0.15,
              }}
            />
          </div>

          {/* Center Card */}
          <div className="level-2-panel p-10 rounded-[32px] border border-outline-variant/20 flex flex-col items-center text-center max-w-2xl relative z-10 glow-accent shadow-2xl">
            {/* Hero Icon */}
            <div className="relative mb-8 group cursor-pointer" onClick={() => void runAudit()}>
              <div className="absolute inset-0 bg-primary rounded-full blur-xl opacity-20 group-hover:opacity-40 transition-opacity duration-500" />
              <div className="w-32 h-32 level-2-panel rounded-full flex items-center justify-center border border-outline-variant/30 relative z-10 shadow-[0_0_40px_rgba(0,0,0,0.5)]">
                <span
                  className="material-symbols-outlined text-[64px] text-primary transition-transform duration-300 group-hover:scale-110"
                  style={{ fontVariationSettings: "'FILL' 1" }}
                >
                  admin_panel_settings
                </span>
              </div>
            </div>

            <h2 className="font-display-lg text-display-lg text-on-surface mb-4">
              Ready to Audit Workspace Security
            </h2>

            <p className="font-ui-label-reg text-ui-label-reg text-on-surface-variant mb-8 max-w-lg leading-relaxed">
              The Verification Agent will analyze your active workspace repository to detect vulnerabilities including <span className="font-code-sm text-code-sm text-secondary bg-secondary/10 px-1 rounded">SQLi</span>, exposed API secrets, missing input boundary sanitization, and insecure dependencies.
            </p>

            {/* Action CTA Button */}
            <button
              onClick={() => void runAudit()}
              className="bg-primary-container text-[#0a0a0c] font-ui-label-bold text-ui-label-bold px-8 py-4 rounded-full flex items-center gap-3 hover:bg-primary transition-all shadow-[0_0_20px_rgba(0,218,243,0.25)] hover:shadow-[0_0_30px_rgba(0,218,243,0.45)] hover:scale-[1.02] cursor-pointer"
            >
              <span className="material-symbols-outlined text-2xl">play_circle</span>
              <span>Run Security Audit Now</span>
            </button>
          </div>

          <div className="absolute bottom-6 left-6 right-6 flex justify-between items-end pointer-events-none opacity-50 hidden md:flex">
            <div className="font-code-sm text-code-sm text-on-surface-variant font-mono">
              Target: <span className="text-on-surface font-semibold">{workspace?.path ?? "No active directory"}</span>
            </div>
            <div className="font-code-sm text-code-sm text-on-surface-variant flex items-center gap-2 font-mono">
              <span className="w-2 h-2 rounded-full bg-outline" /> Auditor: Ready
            </div>
          </div>
        </main>
      ) : (
        /* ── Report Results View ───────────────────────────────────────────── */
        <main className="flex-1 flex flex-col min-h-0 overflow-y-auto p-6 space-y-6">
          {/* Top Score & Metrics Bar */}
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
            <div className="bg-surface-container-low rounded-xl border border-surface-container-high p-5 flex items-center justify-between col-span-1 shadow-md">
              <div>
                <span className="font-caption text-caption text-on-surface-variant uppercase tracking-wider block">Security Score</span>
                <span className="text-3xl font-black text-primary-container mt-1 block">{report.score}/100</span>
              </div>
              <span className="material-symbols-outlined text-primary-container text-4xl" style={{ fontVariationSettings: "'FILL' 1" }}>
                verified
              </span>
            </div>

            <div className="bg-surface-container-low rounded-xl border border-surface-container-high p-5 flex items-center justify-between shadow-md">
              <div>
                <span className="font-caption text-caption text-error uppercase tracking-wider block">Critical</span>
                <span className="text-2xl font-bold text-error mt-1 block">{counts.critical}</span>
              </div>
            </div>

            <div className="bg-surface-container-low rounded-xl border border-surface-container-high p-5 flex items-center justify-between shadow-md">
              <div>
                <span className="font-caption text-caption text-amber-400 uppercase tracking-wider block">High</span>
                <span className="text-2xl font-bold text-amber-400 mt-1 block">{counts.high}</span>
              </div>
            </div>

            <div className="bg-surface-container-low rounded-xl border border-surface-container-high p-5 flex items-center justify-between shadow-md">
              <div>
                <span className="font-caption text-caption text-secondary uppercase tracking-wider block">Medium</span>
                <span className="text-2xl font-bold text-secondary mt-1 block">{counts.medium}</span>
              </div>
            </div>

            <div className="bg-surface-container-low rounded-xl border border-surface-container-high p-5 flex items-center justify-between shadow-md">
              <div>
                <span className="font-caption text-caption text-on-surface-variant uppercase tracking-wider block">Low</span>
                <span className="text-2xl font-bold text-on-surface-variant mt-1 block">{counts.low}</span>
              </div>
            </div>
          </div>

          {/* Action & Filter Row */}
          <div className="flex justify-between items-center flex-wrap gap-4">
            <div className="flex gap-2">
              {["all", "critical", "high", "medium", "low"].map((sev) => (
                <button
                  key={sev}
                  onClick={() => setSelectedSeverity(sev)}
                  className={`px-3.5 py-1.5 rounded-full font-caption text-caption uppercase font-bold transition-all cursor-pointer ${
                    selectedSeverity === sev
                      ? "bg-primary-container text-[#001f24] shadow-md"
                      : "bg-surface-container-high text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  {sev}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={handleDownloadMarkdown}
                className="bg-surface-container-high hover:bg-surface-variant border border-outline-variant/30 text-on-surface px-4 py-2 rounded-full font-ui-label-bold text-xs flex items-center gap-2 transition-colors cursor-pointer shadow-sm"
              >
                <Download size={13} />
                <span>Download Report (.md)</span>
              </button>

              <button
                onClick={() => setShowSaveModal(true)}
                className="bg-primary-container text-[#001f24] hover:bg-primary-fixed px-4 py-2 rounded-full font-ui-label-bold text-xs flex items-center gap-2 transition-all shadow-md cursor-pointer"
              >
                <FileText size={13} />
                <span>Save to Workspace</span>
              </button>

              <button
                onClick={() => void runAudit()}
                className="bg-surface-container-high hover:bg-surface-variant border border-outline-variant/30 text-on-surface px-4 py-2 rounded-full text-xs font-bold flex items-center gap-1.5 transition-colors cursor-pointer"
              >
                <RotateCcw size={12} />
                <span>Re-run Audit</span>
              </button>
            </div>
          </div>

          {/* Findings List & Details Grid */}
          <div className="grid grid-cols-1 md:grid-cols-12 gap-6 flex-1 min-h-0">
            {/* Left List */}
            <div className="md:col-span-5 space-y-3 overflow-y-auto max-h-[500px] pr-2">
              {filteredFindings.length === 0 ? (
                <div className="p-8 text-center bg-surface-container-low rounded-xl border border-surface-container-high text-on-surface-variant text-xs space-y-2">
                  <CheckCircle2 size={24} className="mx-auto text-emerald-400" />
                  <p>No security findings match the selected severity filter.</p>
                </div>
              ) : (
                filteredFindings.map((finding) => (
                  <div
                    key={finding.id}
                    onClick={() => setSelectedFinding(finding)}
                    className={`p-4 rounded-xl border transition-all cursor-pointer shadow-md ${
                      selectedFinding?.id === finding.id
                        ? "bg-surface-container-high border-primary-container/50 shadow-lg shadow-primary-container/5"
                        : "bg-surface-container-low border-surface-container-high hover:border-outline-variant/40"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase font-mono ${
                        finding.severity.toLowerCase() === "critical" || finding.severity.toLowerCase() === "high"
                          ? "bg-error/20 text-error border border-error/30"
                          : finding.severity.toLowerCase() === "medium"
                            ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                            : "bg-secondary/20 text-secondary border border-secondary/30"
                      }`}>
                        {finding.severity}
                      </span>
                      <span className="font-mono text-[11px] text-on-surface-variant">
                        {finding.cwe_id || finding.rule_id || "SAST"}
                      </span>
                    </div>
                    <h4 className="font-ui-label-bold text-ui-label-bold text-on-surface mb-1 truncate">
                      {finding.title || finding.message || "Vulnerability Detected"}
                    </h4>
                    <span className="font-code-sm text-code-sm text-outline-variant truncate block">
                      {finding.file}:{finding.line}
                    </span>
                  </div>
                ))
              )}
            </div>

            {/* Right Details Panel */}
            <div className="md:col-span-7 bg-surface-container-low rounded-xl border border-surface-container-high p-6 flex flex-col gap-4 shadow-md">
              {selectedFinding ? (
                <>
                  <div className="border-b border-surface-variant pb-4">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="px-2.5 py-0.5 rounded text-xs font-bold uppercase font-mono bg-error/20 text-error border border-error/30">
                        {selectedFinding.severity}
                      </span>
                      <span className="font-mono text-xs text-on-surface-variant">
                        {selectedFinding.cwe_id || selectedFinding.rule_id}
                      </span>
                    </div>
                    <h3 className="font-headline-md text-headline-md text-on-surface font-bold">
                      {selectedFinding.title || selectedFinding.message}
                    </h3>
                    <p className="font-code-sm text-code-sm text-primary mt-1 font-mono">
                      {selectedFinding.file}:{selectedFinding.line}
                    </p>
                  </div>

                  {selectedFinding.description && (
                    <p className="text-xs text-on-surface-variant leading-relaxed">
                      {selectedFinding.description}
                    </p>
                  )}

                  {(selectedFinding.code_snippet || selectedFinding.snippet) && (
                    <div>
                      <span className="font-caption text-caption text-on-surface-variant uppercase tracking-wider block mb-1.5">
                        Affected Code Snippet
                      </span>
                      <div className="bg-[#0a0a0c] border border-surface-variant rounded-lg p-3 font-code-sm text-code-sm text-error whitespace-pre-wrap font-mono">
                        {selectedFinding.code_snippet || selectedFinding.snippet}
                      </div>
                    </div>
                  )}

                  {(selectedFinding.fix_suggestion || selectedFinding.remediation) && (
                    <div className="mt-2 bg-emerald-500/5 border border-emerald-500/20 rounded-xl p-4">
                      <div className="flex items-center gap-2 text-emerald-400 font-bold text-xs mb-1.5">
                        <CheckCircle2 size={14} />
                        <span>Recommended Remediation</span>
                      </div>
                      <p className="text-xs text-on-surface leading-relaxed">
                        {selectedFinding.fix_suggestion || selectedFinding.remediation}
                      </p>
                    </div>
                  )}
                </>
              ) : (
                <div className="h-full flex items-center justify-center text-xs text-on-surface-variant/50 p-8 text-center">
                  Select a security finding on the left to inspect details.
                </div>
              )}
            </div>
          </div>
        </main>
      )}

      {/* ── Save to Workspace Modal ────────────────────────────────────────── */}
      {showSaveModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="rounded-2xl p-6 border border-surface-container-high max-w-md w-full flex flex-col gap-4 bg-[#1e1f24] text-on-surface shadow-2xl">
            <div className="flex justify-between items-center">
              <div className="flex items-center gap-2 text-primary font-bold text-sm">
                <FileText size={18} />
                <span>Save Security Audit to Workspace?</span>
              </div>
              <button onClick={() => setShowSaveModal(false)} className="text-on-surface-variant hover:text-on-surface">
                <X size={16} />
              </button>
            </div>

            <p className="text-xs text-on-surface-variant leading-relaxed">
              This will write the generated audit report to <code className="text-primary font-mono font-bold bg-[#131315] px-1.5 py-0.5 rounded">SECURITY_AUDIT.md</code> inside your workspace root (<span className="font-mono text-on-surface font-semibold">{workspace?.name}</span>).
            </p>

            {savedSuccess ? (
              <div className="p-3 rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-xs font-bold flex items-center gap-2">
                <Check size={16} />
                <span>Saved SECURITY_AUDIT.md successfully!</span>
              </div>
            ) : (
              <div className="flex justify-end gap-3 mt-2">
                <button
                  onClick={() => setShowSaveModal(false)}
                  disabled={savingFile}
                  className="px-4 py-1.5 rounded-full border border-outline text-xs font-bold text-on-surface hover:bg-surface-variant transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  onClick={() => void handleSaveToWorkspace()}
                  disabled={savingFile}
                  className="px-5 py-1.5 rounded-full bg-primary-container text-[#001f24] text-xs font-bold hover:bg-primary-fixed flex items-center gap-1.5 transition-all shadow-md cursor-pointer disabled:opacity-40"
                >
                  {savingFile ? <Loader2 size={12} className="animate-spin" /> : <Check size={14} />}
                  <span>Authorize &amp; Save</span>
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
