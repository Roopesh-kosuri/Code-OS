import { useEffect, useState } from "react";
import {
  ShieldCheck, ShieldAlert, Shield, AlertTriangle, CheckCircle2,
  Lock, Key, Database, Terminal, FileCode, Cpu, Download, FileText,
  Sparkles, RefreshCw, ChevronRight, Zap, Eye, Check, X
} from "lucide-react";
import { api } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { useAIStore } from "../../stores/aiStore";
import { ProviderSelector, type ProviderConfig } from "../../components/ui/ProviderSelector";
import { getPreset } from "../../lib/providerPresets";

type Finding = {
  id: string;
  file: string;
  line: number;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  category: "secrets" | "injection" | "validation" | "resource_limits" | "auth_web";
  cwe_id?: string;
  title: string;
  description: string;
  fix_suggestion: string;
  code_snippet: string;
};

type AuditReport = {
  summary: string;
  score: number;
  risk_level: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "CLEAN";
  duration: number;
  files_analyzed: number;
  category_scores: {
    secrets: number;
    injection: number;
    validation: number;
    resource_limits: number;
    auth_web: number;
  };
  findings: Finding[];
  model_used: string;
  provider_used: string;
};

export function CodeVerifierPanel() {
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const [report, setReport] = useState<AuditReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedSeverity, setSelectedSeverity] = useState<string>("ALL");
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [savingFile, setSavingFile] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);

  // Provider selector state
  const [providerConfig, setProviderConfig] = useState<ProviderConfig>({
    preset: "auto",
    model: "",
  });
  const [configuredKeys, setConfiguredKeys] = useState<string[]>([]);
  const models = useAIStore((s) => s.models);

  useEffect(() => {
    void api.get<{ provider_id: string; configured: boolean }[]>("/api/settings/api-keys")
      .then((keys) => setConfiguredKeys(keys.filter((k) => k.configured).map((k) => k.provider_id)))
      .catch(() => undefined);
  }, []);

  const buildProviderConfig = () => {
    const presetObj = getPreset(providerConfig.preset);
    return {
      provider: presetObj?.provider || (providerConfig.preset === "ollama" ? "ollama" : "openai-compatible"),
      preset: providerConfig.preset,
      model: providerConfig.model || presetObj?.model_example || "llama3",
      base_url: providerConfig.base_url || presetObj?.base_url,
      api_key_provider: providerConfig.api_key_provider || presetObj?.api_key_provider,
    };
  };

  const handleRunAudit = async () => {
    if (!currentWorkspace) return;
    setLoading(true);
    try {
      const data = await api.post<AuditReport>("/api/agents/audit", {
        workspace: currentWorkspace.path,
        provider_config: buildProviderConfig(),
      });
      setReport(data);
    } catch (err) {
      alert("Failed to run security audit: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  const generateMarkdownReport = (rep: AuditReport): string => {
    let md = `# Security Audit & Code Verification Report\n\n`;
    md += `**Workspace:** \`${currentWorkspace?.path || "Current Project"}\`\n`;
    md += `**Date:** ${new Date().toLocaleString()}\n`;
    md += `**Production Readiness Score:** ${rep.score}/100 (${rep.risk_level})\n`;
    md += `**Model:** ${rep.model_used} (${rep.provider_used})\n\n`;
    md += `## Executive Summary\n${rep.summary}\n\n`;
    md += `## Category Sub-Scores\n`;
    md += `- Secrets & Credentials: ${rep.category_scores.secrets}/100\n`;
    md += `- Injection Vulnerabilities: ${rep.category_scores.injection}/100\n`;
    md += `- Input Validation: ${rep.category_scores.validation}/100\n`;
    md += `- Resource Exhaustion (DoS): ${rep.category_scores.resource_limits}/100\n`;
    md += `- Auth & Web Vulnerabilities: ${rep.category_scores.auth_web}/100\n\n`;
    const findingsList = rep.findings || [];
    md += `## Findings (${findingsList.length})\n\n`;

    findingsList.forEach((f, idx) => {
      md += `### ${idx + 1}. [${f.severity}] ${f.title} (${f.cwe_id || "CWE"})\n`;
      md += `- **File:** \`${f.file}\` (Line ${f.line})\n`;
      md += `- **Category:** ${f.category}\n`;
      md += `- **Description:** ${f.description}\n`;
      md += `- **Fix Suggestion:** ${f.fix_suggestion}\n`;
      if (f.code_snippet) {
        md += `\n\`\`\`\n${f.code_snippet}\n\`\`\`\n`;
      }
      md += `\n---\n\n`;
    });

    return md;
  };

  const handleDownloadMarkdown = () => {
    if (!report) return;
    const md = generateMarkdownReport(report);
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `SECURITY_AUDIT_${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleSaveToWorkspace = async () => {
    if (!report || !currentWorkspace) return;
    setSavingFile(true);
    try {
      const md = generateMarkdownReport(report);
      await api.post("/api/agents/audit/save-report", {
        workspace: currentWorkspace.path,
        markdown_content: md,
      });
      setSavedSuccess(true);
      setTimeout(() => {
        setSavedSuccess(false);
        setShowSaveModal(false);
      }, 1500);
    } catch (err) {
      alert("Failed to save SECURITY_AUDIT.md: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setSavingFile(false);
    }
  };

  if (!currentWorkspace) {
    return (
      <section className="flex h-full flex-col items-center justify-center p-4 text-center space-y-3 select-none bg-[var(--surface)] text-on-surface">
        <Shield size={32} className="text-slate-600 animate-pulse" />
        <span className="text-xs text-slate-400 font-mono">Open a workspace to access the Security Auditor Agent.</span>
      </section>
    );
  }

  const filteredFindings = (report?.findings || []).filter((f) => {
    if (selectedSeverity === "ALL") return true;
    return f.severity === selectedSeverity;
  });

  const getScoreColor = (score: number) => {
    if (score >= 90) return "text-emerald-400 border-emerald-500/40 bg-emerald-950/20";
    if (score >= 75) return "text-cyan-400 border-cyan-500/40 bg-cyan-950/20";
    if (score >= 50) return "text-amber-400 border-amber-500/40 bg-amber-950/20";
    return "text-rose-400 border-rose-500/40 bg-rose-950/20";
  };

  const getSeverityBadge = (sev: string) => {
    switch (sev) {
      case "CRITICAL": return <span className="bg-rose-500/10 text-rose-400 border border-rose-500/30 px-2 py-0.5 rounded text-[10px] font-bold">CRITICAL</span>;
      case "HIGH": return <span className="bg-orange-500/10 text-orange-400 border border-orange-500/30 px-2 py-0.5 rounded text-[10px] font-bold">HIGH</span>;
      case "MEDIUM": return <span className="bg-amber-500/10 text-amber-400 border border-amber-500/30 px-2 py-0.5 rounded text-[10px] font-bold">MEDIUM</span>;
      default: return <span className="bg-slate-500/10 text-slate-400 border border-slate-500/30 px-2 py-0.5 rounded text-[10px] font-bold">LOW</span>;
    }
  };

  return (
    <main data-testid="code-verifier-panel" className="flex-1 overflow-y-auto p-4 md:p-6 flex flex-col gap-6 bg-[var(--surface)] text-on-surface h-full select-none font-mono">
      {/* Top Header */}
      <div className="flex justify-between items-center pb-4 border-b border-white/5 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10 border border-primary/30 text-primary">
            <ShieldCheck size={24} />
          </div>
          <div>
            <h1 className="font-bold text-on-surface text-base sm:text-lg tracking-tight">Code Verification Agent</h1>
            <p className="text-xs text-on-surface-variant">Multi-model SAST & production-readiness security auditor</p>
          </div>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <ProviderSelector
            value={providerConfig}
            onChange={setProviderConfig}
            configuredKeys={configuredKeys}
            models={models}
            compact
          />

          <button
            onClick={() => void handleRunAudit()}
            disabled={loading}
            className="bg-primary/10 text-primary border border-primary/40 hover:bg-primary/20 px-4 py-2 rounded-full text-xs font-bold transition-all flex items-center gap-2 shadow-[0_0_15px_rgba(0,229,255,0.15)] disabled:opacity-50"
          >
            {loading ? (
              <>
                <RefreshCw size={14} className="animate-spin" />
                <span>Auditing Workspace...</span>
              </>
            ) : (
              <>
                <Sparkles size={14} />
                <span>Run Security Audit</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      {report ? (
        <div className="flex flex-col gap-6">
          {/* Dashboard Summary Cards */}
          <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
            {/* Score Ring / Dial Card */}
            <div className={`md:col-span-4 glass-panel rounded-lg p-5 border flex flex-col justify-between items-center text-center ${getScoreColor(report.score)}`}>
              <span className="text-[10px] uppercase font-bold tracking-wider opacity-80">Production Readiness Score</span>
              <div className="my-3 relative flex items-center justify-center">
                <div className="text-4xl font-black font-mono tracking-tighter">{report.score}</div>
                <span className="text-xs font-bold text-slate-400 ml-1">/ 100</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-wider">{report.risk_level} RISK</span>
                <span className="text-[10px] text-slate-400">({report.findings?.length ?? 0} findings)</span>
              </div>
            </div>

            {/* Category Breakdown */}
            <div className="md:col-span-8 glass-panel rounded-lg p-5 border border-white/5 bg-surface-container-lowest flex flex-col justify-between">
              <div className="flex justify-between items-center mb-3">
                <span className="text-xs font-bold uppercase tracking-wider text-on-surface">Category Security Sub-Scores</span>
                <span className="text-[10px] text-slate-400">Model: {report.model_used}</span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-center text-xs">
                <div className="p-2 rounded bg-surface-container border border-white/5">
                  <div className="text-[9px] text-slate-400 mb-1">🔑 Secrets</div>
                  <div className="font-bold text-emerald-400">{report.category_scores?.secrets ?? 100}</div>
                </div>
                <div className="p-2 rounded bg-surface-container border border-white/5">
                  <div className="text-[9px] text-slate-400 mb-1">💉 Injection</div>
                  <div className="font-bold text-cyan-400">{report.category_scores?.injection ?? 100}</div>
                </div>
                <div className="p-2 rounded bg-surface-container border border-white/5">
                  <div className="text-[9px] text-slate-400 mb-1">🛡️ Validation</div>
                  <div className="font-bold text-amber-400">{report.category_scores?.validation ?? 100}</div>
                </div>
                <div className="p-2 rounded bg-surface-container border border-white/5">
                  <div className="text-[9px] text-slate-400 mb-1">⚡ DoS Limits</div>
                  <div className="font-bold text-violet-400">{report.category_scores?.resource_limits ?? 100}</div>
                </div>
                <div className="p-2 rounded bg-surface-container border border-white/5">
                  <div className="text-[9px] text-slate-400 mb-1">🌐 Web/Auth</div>
                  <div className="font-bold text-blue-400">{report.category_scores?.auth_web ?? 100}</div>
                </div>
              </div>
            </div>
          </div>

          {/* Action Toolbar */}
          <div className="flex justify-between items-center flex-wrap gap-3 glass-panel p-3 rounded-lg border border-white/5">
            {/* Filter Pills */}
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[10px] text-slate-400 uppercase font-bold mr-1">Filter:</span>
              {["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW"].map((sev) => (
                <button
                  key={sev}
                  onClick={() => setSelectedSeverity(sev)}
                  className={`text-[10px] font-bold px-2.5 py-1 rounded border transition-colors ${
                    selectedSeverity === sev
                      ? "bg-primary/20 text-primary border-primary/40"
                      : "bg-surface-container text-slate-400 border-white/5 hover:text-on-surface"
                  }`}
                >
                  {sev}
                </button>
              ))}
            </div>

            {/* Export Buttons */}
            <div className="flex items-center gap-2">
              <button
                onClick={handleDownloadMarkdown}
                className="text-xs bg-surface-container border border-white/10 hover:bg-white/5 text-on-surface px-3 py-1.5 rounded flex items-center gap-1.5 font-bold transition-all"
              >
                <Download size={13} />
                <span>Download Report (.md)</span>
              </button>
              <button
                onClick={() => setShowSaveModal(true)}
                className="text-xs bg-primary-container text-on-primary-container hover:opacity-90 px-3 py-1.5 rounded flex items-center gap-1.5 font-bold transition-all shadow-[0_0_10px_rgba(0,229,255,0.2)]"
              >
                <FileText size={13} />
                <span>Save to Workspace</span>
              </button>
            </div>
          </div>

          {/* Findings List */}
          <div className="flex flex-col gap-3">
            <div className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Audit Findings ({filteredFindings.length})
            </div>

            {filteredFindings.length === 0 ? (
              <div className="p-8 text-center glass-panel rounded-lg border border-white/5 text-slate-400 text-xs">
                <CheckCircle2 size={24} className="mx-auto text-emerald-400 mb-2" />
                No security findings matching the selected filter.
              </div>
            ) : (
              filteredFindings.map((finding) => (
                <div
                  key={finding.id}
                  className="glass-panel rounded-lg p-4 border border-white/5 bg-surface-container-lowest flex flex-col gap-2 relative overflow-hidden"
                >
                  {/* Left accent bar */}
                  <div className={`absolute top-0 left-0 w-1 h-full ${
                    finding.severity === "CRITICAL" ? "bg-rose-500" :
                    finding.severity === "HIGH" ? "bg-amber-500" :
                    finding.severity === "MEDIUM" ? "bg-yellow-500" : "bg-slate-500"
                  }`} />

                  {/* Finding Title & Badges */}
                  <div className="flex justify-between items-start flex-wrap gap-2">
                    <div className="flex items-center gap-2">
                      <span className={`text-[9px] px-2 py-0.5 rounded border uppercase ${getSeverityBadge(finding.severity)}`}>
                        {finding.severity}
                      </span>
                      {finding.cwe_id && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded border border-white/10 text-slate-400 font-mono">
                          {finding.cwe_id}
                        </span>
                      )}
                      <span className="text-xs font-bold text-on-surface">{finding.title}</span>
                    </div>

                    <span className="text-[10px] text-slate-400 font-mono bg-surface-container px-2 py-0.5 rounded border border-white/5">
                      {finding.file}:{finding.line}
                    </span>
                  </div>

                  {/* Description */}
                  <p className="text-xs text-slate-300 leading-relaxed">{finding.description}</p>

                  {/* Code Snippet */}
                  {finding.code_snippet && (
                    <div className="bg-surface-container-lowest p-2.5 rounded border border-white/5 text-[11px] font-mono overflow-x-auto text-rose-300">
                      {finding.code_snippet}
                    </div>
                  )}

                  {/* Fix Suggestion */}
                  <div className="mt-1 p-2.5 rounded bg-emerald-950/20 border border-emerald-800/30 text-emerald-300 text-xs">
                    <span className="font-bold block mb-0.5 text-emerald-400">💡 Suggested Fix:</span>
                    {finding.fix_suggestion}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      ) : (
        /* Empty State */
        <div className="flex-1 glass-panel rounded-lg border border-white/5 flex flex-col items-center justify-center p-8 text-center space-y-4">
          <div className="p-4 rounded-full bg-primary/10 border border-primary/30 text-primary">
            <ShieldCheck size={36} />
          </div>
          <div>
            <h2 className="text-base font-bold text-on-surface">Ready to Audit Workspace Security</h2>
            <p className="text-xs text-slate-400 max-w-md mt-1 leading-relaxed">
              Run a multi-pass security verification check to audit SQL injection, exposed API keys/secrets, missing input validation, DDoS/resource limits, and web vulnerabilities.
            </p>
          </div>
          <button
            onClick={() => void handleRunAudit()}
            disabled={loading}
            className="bg-primary/10 text-primary border border-primary/40 hover:bg-primary/20 px-6 py-2.5 rounded-full text-xs font-bold transition-all flex items-center gap-2 shadow-[0_0_15px_rgba(0,229,255,0.15)] disabled:opacity-50"
          >
            <Sparkles size={14} />
            <span>Run Security Audit Now</span>
          </button>
        </div>
      )}

      {/* Explicit Save Confirmation Modal */}
      {showSaveModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="glass-panel rounded-xl p-6 border border-white/10 max-w-md w-full flex flex-col gap-4 bg-surface-container-high text-on-surface">
            <div className="flex justify-between items-center">
              <div className="flex items-center gap-2 text-primary font-bold text-sm">
                <FileText size={18} />
                <span>Save Security Audit to Workspace?</span>
              </div>
              <button onClick={() => setShowSaveModal(false)} className="text-slate-400 hover:text-on-surface">
                <X size={16} />
              </button>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              This will write the generated audit report to <code className="text-primary font-mono font-bold bg-surface-container px-1 py-0.5 rounded">SECURITY_AUDIT.md</code> inside your workspace root (<span className="font-mono text-slate-400">{currentWorkspace.name}</span>).
            </p>

            {savedSuccess ? (
              <div className="p-3 rounded bg-emerald-950/40 border border-emerald-600/40 text-emerald-300 text-xs font-bold flex items-center gap-2">
                <Check size={16} />
                <span>Saved SECURITY_AUDIT.md successfully!</span>
              </div>
            ) : (
              <div className="flex justify-end gap-2 mt-2">
                <button
                  onClick={() => setShowSaveModal(false)}
                  disabled={savingFile}
                  className="px-4 py-1.5 rounded border border-white/10 text-xs font-bold text-slate-300 hover:bg-white/5"
                >
                  Cancel
                </button>
                <button
                  onClick={() => void handleSaveToWorkspace()}
                  disabled={savingFile}
                  className="px-4 py-1.5 rounded bg-primary text-slate-950 text-xs font-bold hover:bg-primary/90 flex items-center gap-1.5"
                >
                  {savingFile ? <RefreshCw size={12} className="animate-spin" /> : <Check size={12} />}
                  <span>Authorize & Save</span>
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </main>
  );
}
