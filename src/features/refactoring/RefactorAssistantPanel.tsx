import React, { useState } from 'react';
import { 
  useRefactorStore, 
  CodeSmell, 
  RefactorPreview, 
  RefactorRequest 
} from './refactorStore';
import { RefactorContextMenu } from './RefactorContextMenu';
import { 
  Wand2, 
  Sparkles, 
  AlertTriangle, 
  AlertCircle, 
  Info, 
  CheckCircle2, 
  XCircle, 
  ShieldAlert, 
  ShieldCheck, 
  Layers, 
  FileCode2, 
  ArrowRight, 
  Play, 
  Check, 
  X, 
  ChevronRight, 
  RefreshCw,
  GitCommit,
  Copy,
  Zap
} from 'lucide-react';

export const RefactorAssistantPanel: React.FC = () => {
  const {
    codeSmells,
    duplicates,
    complexityMetrics,
    refactorPreview,
    verificationStatus,
    isAnalyzing,
    isVerifying,
    isApplying,
    error,
    activeSmell,
    isQuickFixOpen,
    ghostTextEnabled,
    smartStagingEnabled,
    analyzeCodebase,
    previewRefactor,
    verifyRefactor,
    applyRefactor,
    setActiveSmell,
    setQuickFixOpen,
    clearPreview,
    toggleGhostText,
    toggleSmartStaging
  } = useRefactorStore();

  const [filterSeverity, setFilterSeverity] = useState<string>('all');
  const [activeTab, setActiveTab] = useState<'smells' | 'duplicates' | 'complexity'>('smells');
  const [selectedRefactorType, setSelectedRefactorType] = useState<string>('extract_function');

  // Filter smells
  const filteredSmells = codeSmells.filter(smell => {
    if (filterSeverity === 'all') return true;
    return smell.severity.toLowerCase() === filterSeverity.toLowerCase();
  });

  const criticalCount = codeSmells.filter(s => s.severity.toLowerCase() === 'critical').length;
  const warningCount = codeSmells.filter(s => s.severity.toLowerCase() === 'warning').length;
  const infoCount = codeSmells.filter(s => s.severity.toLowerCase() === 'info').length;

  const handleOpenQuickFix = (smell: CodeSmell) => {
    setActiveSmell(smell);
    setQuickFixOpen(true);
    // Suggest refactor type based on ruleId
    let type = 'extract_function';
    if (smell.ruleId === 'long_function') type = 'extract_function';
    else if (smell.ruleId === 'complex_conditional' || smell.ruleId === 'deep_nesting') type = 'flatten_conditionals';
    else if (smell.ruleId === 'duplicated_code') type = 'deduplicate';
    else if (smell.ruleId === 'dead_code' || smell.ruleId === 'unused_imports') type = 'remove_dead_code';
    else if (smell.ruleId === 'god_class') type = 'extract_class';
    setSelectedRefactorType(type);

    previewRefactor({
      type,
      filePath: smell.filePath,
      ruleId: smell.ruleId,
      symbolName: smell.symbolName,
      startLine: smell.line,
      endLine: smell.endLine,
      description: `Fix ${smell.ruleId} at ${smell.filePath}:${smell.line}`
    });
  };

  const handleApply = async () => {
    if (!refactorPreview) return;
    await applyRefactor({
      type: refactorPreview.type,
      filePath: refactorPreview.filePath,
      diff: refactorPreview.diff,
      modifiedCode: refactorPreview.modifiedCode,
      changes: refactorPreview.changes
    } as any);
  };

  return (
    <div 
      data-testid="refactor-assistant-panel" 
      className="flex flex-col h-full bg-[#0f111a] text-slate-200 select-none overflow-hidden font-sans border-l border-white/5"
    >
      {/* Top Header */}
      <div className="p-4 border-b border-white/5 bg-[#141724]/80 backdrop-blur-md flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-gradient-to-tr from-cyan-500/20 to-purple-500/20 border border-cyan-500/30 text-cyan-400 shadow-lg shadow-cyan-500/10">
              <Wand2 className="w-5 h-5 animate-pulse" />
            </div>
            <div>
              <h2 className="text-sm font-semibold tracking-wide text-white flex items-center gap-2">
                Refactoring Assistant
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 font-mono">
                  AI-Safe
                </span>
              </h2>
              <p className="text-[11px] text-slate-400">Context-aware restructuring with test safety gating</p>
            </div>
          </div>

          <button
            data-testid="analyze-code-quality-button"
            onClick={() => analyzeCodebase()}
            disabled={isAnalyzing}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white text-xs font-medium shadow-md shadow-cyan-500/20 transition-all active:scale-95 disabled:opacity-50 cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isAnalyzing ? 'animate-spin' : ''}`} />
            <span>{isAnalyzing ? 'Analyzing...' : 'Analyze Code Quality'}</span>
          </button>
        </div>

        {/* Integration Badges & Metrics Bar */}
        <div className="grid grid-cols-4 gap-2 pt-1">
          <div className="bg-[#1b1f33]/60 border border-white/5 rounded-lg p-2 flex flex-col">
            <span className="text-[10px] text-slate-400 uppercase font-mono">Total Smells</span>
            <span className="text-base font-bold text-white mt-0.5">{codeSmells.length}</span>
          </div>
          <div className="bg-[#1b1f33]/60 border border-white/5 rounded-lg p-2 flex flex-col">
            <span className="text-[10px] text-rose-400 uppercase font-mono">Critical</span>
            <span className="text-base font-bold text-rose-400 mt-0.5">{criticalCount}</span>
          </div>
          <div className="bg-[#1b1f33]/60 border border-white/5 rounded-lg p-2 flex flex-col">
            <span className="text-[10px] text-amber-400 uppercase font-mono">Warnings</span>
            <span className="text-base font-bold text-amber-400 mt-0.5">{warningCount}</span>
          </div>
          <div className="bg-[#1b1f33]/60 border border-white/5 rounded-lg p-2 flex flex-col">
            <span className="text-[10px] text-cyan-400 uppercase font-mono">Duplicates</span>
            <span className="text-base font-bold text-cyan-400 mt-0.5">{duplicates.length}</span>
          </div>
        </div>

        {/* Toggle Ghost Text & Smart Staging */}
        <div className="flex items-center justify-between pt-1 border-t border-white/5 text-[11px] text-slate-400">
          <div className="flex items-center gap-3">
            <button 
              onClick={toggleGhostText}
              className={`flex items-center gap-1.5 px-2 py-0.5 rounded transition ${ghostTextEnabled ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30' : 'hover:text-slate-300'}`}
              title="Ghost Text: single-file inline refactor preview"
            >
              <Zap className="w-3 h-3" />
              <span>Ghost Text</span>
            </button>

            <button 
              onClick={toggleSmartStaging}
              className={`flex items-center gap-1.5 px-2 py-0.5 rounded transition ${smartStagingEnabled ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30' : 'hover:text-slate-300'}`}
              title="Smart Staging: multi-file atomic restructuring"
            >
              <GitCommit className="w-3 h-3" />
              <span>Smart Staging</span>
            </button>
          </div>

          <span className="text-[10px] font-mono text-emerald-400/80 flex items-center gap-1">
            <ShieldCheck className="w-3 h-3" />
            Sandbox Gated
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-white/5 px-4 bg-[#121420]">
        <button
          onClick={() => setActiveTab('smells')}
          className={`py-2.5 px-3 text-xs font-medium border-b-2 flex items-center gap-2 transition ${
            activeTab === 'smells' 
              ? 'border-cyan-400 text-cyan-300' 
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <AlertTriangle className="w-3.5 h-3.5" />
          Code Smells ({codeSmells.length})
        </button>
        <button
          onClick={() => setActiveTab('duplicates')}
          className={`py-2.5 px-3 text-xs font-medium border-b-2 flex items-center gap-2 transition ${
            activeTab === 'duplicates' 
              ? 'border-cyan-400 text-cyan-300' 
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Copy className="w-3.5 h-3.5" />
          Duplicates ({duplicates.length})
        </button>
        <button
          onClick={() => setActiveTab('complexity')}
          className={`py-2.5 px-3 text-xs font-medium border-b-2 flex items-center gap-2 transition ${
            activeTab === 'complexity' 
              ? 'border-cyan-400 text-cyan-300' 
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Layers className="w-3.5 h-3.5" />
          Complexity ({complexityMetrics.length})
        </button>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Severity Filter pills for smells */}
        {activeTab === 'smells' && (
          <div className="flex items-center justify-between gap-2 pb-2">
            <div className="flex items-center gap-1.5 text-xs">
              <span className="text-[11px] text-slate-500 mr-1">Filter:</span>
              {(['all', 'critical', 'warning', 'info'] as const).map(sev => (
                <button
                  key={sev}
                  onClick={() => setFilterSeverity(sev)}
                  className={`px-2 py-0.5 rounded-full text-[11px] font-medium capitalize transition ${
                    filterSeverity === sev 
                      ? 'bg-white/10 text-white border border-white/20' 
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {sev}
                </button>
              ))}
            </div>
            <span className="text-[11px] text-slate-500 font-mono">
              Showing {filteredSmells.length} smells
            </span>
          </div>
        )}

        {/* Code Smells List */}
        {activeTab === 'smells' && (
          <div data-testid="code-smells-list" className="space-y-2.5">
            {filteredSmells.length === 0 ? (
              <div className="text-center py-12 text-slate-500 flex flex-col items-center">
                <CheckCircle2 className="w-8 h-8 text-emerald-500/50 mb-2" />
                <p className="text-sm font-medium text-slate-400">No code smells detected</p>
                <p className="text-xs text-slate-500 mt-1">Click "Analyze Code Quality" to inspect the repository</p>
              </div>
            ) : (
              filteredSmells.map(smell => {
                const isCrit = smell.severity.toLowerCase() === 'critical';
                const isWarn = smell.severity.toLowerCase() === 'warning';

                return (
                  <div
                    key={smell.id}
                    data-testid={`code-smell-item-${smell.id}`}
                    className="group bg-[#16192b]/70 hover:bg-[#1a1e33] border border-white/5 hover:border-white/15 rounded-xl p-3.5 transition-all shadow-sm flex flex-col gap-2.5"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        {isCrit ? (
                          <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
                        ) : isWarn ? (
                          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
                        ) : (
                          <Info className="w-4 h-4 text-cyan-400 shrink-0" />
                        )}
                        <span className="text-xs font-semibold text-slate-100 font-mono">
                          {smell.ruleId}
                        </span>
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium uppercase tracking-wider ${
                          isCrit ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' :
                          isWarn ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' :
                          'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                        }`}>
                          {smell.severity}
                        </span>
                      </div>

                      <button
                        data-testid={`quick-fix-btn-${smell.id}`}
                        onClick={() => handleOpenQuickFix(smell)}
                        className="px-2.5 py-1 rounded-md bg-cyan-500/15 hover:bg-cyan-500/25 border border-cyan-500/30 text-cyan-300 text-xs font-medium flex items-center gap-1.5 transition cursor-pointer"
                      >
                        <Sparkles className="w-3 h-3 text-cyan-400" />
                        <span>Quick Fix</span>
                      </button>
                    </div>

                    <p className="text-xs text-slate-300 leading-relaxed">
                      {smell.message}
                    </p>

                    <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono pt-1 border-t border-white/5">
                      <div className="flex items-center gap-1.5 truncate max-w-[80%]">
                        <FileCode2 className="w-3 h-3 text-slate-500" />
                        <span className="truncate">{smell.filePath}:{smell.line}</span>
                      </div>
                      {smell.symbolName && (
                        <span className="text-cyan-400/80 bg-cyan-500/5 px-1.5 py-0.5 rounded">
                          {smell.symbolName}()
                        </span>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}

        {/* Duplicates Tab */}
        {activeTab === 'duplicates' && (
          <div className="space-y-3">
            {duplicates.length === 0 ? (
              <div className="text-center py-12 text-slate-500">
                <Copy className="w-8 h-8 text-slate-600 mb-2 mx-auto" />
                <p className="text-sm">No duplicate blocks found</p>
              </div>
            ) : (
              duplicates.map((dup, i) => (
                <div key={i} className="bg-[#16192b]/70 border border-white/5 rounded-xl p-3.5 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-amber-400 flex items-center gap-1.5">
                      <Copy className="w-3.5 h-3.5" />
                      Duplicate Block #{i + 1} ({dup.lines} lines)
                    </span>
                    <button
                      onClick={() => {
                        previewRefactor({
                          type: 'deduplicate',
                          filePath: dup.instances?.[0]?.file || '',
                          description: `Deduplicate matching block across ${dup.instances?.length || 0} files`
                        });
                        setQuickFixOpen(true);
                      }}
                      className="px-2 py-1 rounded bg-amber-500/15 text-amber-300 text-xs font-medium border border-amber-500/30 hover:bg-amber-500/25 transition"
                    >
                      Extract Common Helper
                    </button>
                  </div>
                  <div className="space-y-1 text-[11px] font-mono text-slate-400">
                    {(dup.instances || []).map((inst: any, idx: number) => (
                      <div key={idx} className="flex items-center gap-2">
                        <ArrowRight className="w-3 h-3 text-slate-500" />
                        <span>{inst.file}:{inst.start_line}-{inst.end_line}</span>
                      </div>
                    ))}
                  </div>
                  {dup.snippet && (
                    <pre className="p-2 rounded bg-black/40 text-[11px] font-mono text-slate-300 overflow-x-auto border border-white/5">
                      {dup.snippet}
                    </pre>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {/* Complexity Tab */}
        {activeTab === 'complexity' && (
          <div className="space-y-2.5">
            {complexityMetrics.length === 0 ? (
              <div className="text-center py-12 text-slate-500">
                <Layers className="w-8 h-8 text-slate-600 mb-2 mx-auto" />
                <p className="text-sm">No function complexity recorded yet</p>
              </div>
            ) : (
              (complexityMetrics || []).map((func: any, i: number) => (
                <div key={i} className="bg-[#16192b]/70 border border-white/5 rounded-xl p-3 flex items-center justify-between">
                  <div className="space-y-0.5">
                    <div className="text-xs font-mono font-semibold text-slate-200">
                      {func.name}()
                    </div>
                    <div className="text-[11px] text-slate-400 font-mono">
                      {func.file}:{func.line} • {func.lines} lines
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="text-right">
                      <div className="text-[10px] text-slate-400 uppercase">Cyclomatic</div>
                      <div className={`text-xs font-bold font-mono ${func.cyclomatic > 10 ? 'text-rose-400' : 'text-slate-300'}`}>
                        {func.cyclomatic}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-[10px] text-slate-400 uppercase">Cognitive</div>
                      <div className={`text-xs font-bold font-mono ${func.cognitive > 15 ? 'text-amber-400' : 'text-slate-300'}`}>
                        {func.cognitive}
                      </div>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* QUICK FIX MODAL / DIALOG */}
      {isQuickFixOpen && (
        <div 
          data-testid="quick-fix-dialog" 
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-in fade-in duration-150"
        >
          <div className="bg-[#141829] border border-cyan-500/30 rounded-2xl w-full max-w-2xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
            {/* Dialog Header */}
            <div className="p-4 border-b border-white/10 bg-[#191e33] flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-lg bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                  <Sparkles className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    AI Safe Refactor Preview
                    {activeSmell && (
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">
                        {activeSmell.ruleId}
                      </span>
                    )}
                  </h3>
                  <p className="text-[11px] text-slate-400">
                    {refactorPreview?.explanation || 'Previewing code restructuring'}
                  </p>
                </div>
              </div>

              <button
                onClick={() => setQuickFixOpen(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Dialog Body */}
            <div className="p-4 overflow-y-auto space-y-4 flex-1">
              {/* Pattern Selection / Action details */}
              <div className="flex items-center justify-between text-xs bg-[#101322] p-2.5 rounded-lg border border-white/5">
                <div className="flex items-center gap-2">
                  <span className="text-slate-400">Refactoring Pattern:</span>
                  <span className="font-mono font-semibold text-cyan-300 uppercase text-[11px]">
                    {refactorPreview?.type || selectedRefactorType}
                  </span>
                </div>
                {refactorPreview?.impact && (
                  <div className="flex items-center gap-3 text-[11px] font-mono">
                    <span className="text-emerald-400">
                      Δ Lines: {((refactorPreview.impact as any).linesDelta || 0) > 0 ? `+${(refactorPreview.impact as any).linesDelta}` : (refactorPreview.impact as any).linesDelta}
                    </span>
                    <span className="text-cyan-400">
                      Complexity: {(refactorPreview.impact as any).complexityDelta || 0}
                    </span>
                  </div>
                )}
              </div>

              {/* Code Diff Preview Box */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-[11px] text-slate-400">
                  <span className="font-semibold uppercase tracking-wider text-[10px]">Diff Preview</span>
                  <span className="font-mono text-slate-500">{refactorPreview?.filePath}</span>
                </div>

                <div 
                  data-testid="refactor-diff-preview" 
                  className="bg-[#0b0d14] border border-white/10 rounded-xl p-3 font-mono text-xs overflow-x-auto max-h-64 leading-relaxed"
                >
                  {refactorPreview?.diff ? (
                    refactorPreview.diff.split('\n').map((line, idx) => {
                      const isAdded = line.startsWith('+') && !line.startsWith('+++');
                      const isRemoved = line.startsWith('-') && !line.startsWith('---');
                      const isHeader = line.startsWith('@@') || line.startsWith('---') || line.startsWith('+++');

                      return (
                        <div
                          key={idx}
                          className={`${
                            isAdded ? 'bg-emerald-500/15 text-emerald-300' :
                            isRemoved ? 'bg-rose-500/15 text-rose-300' :
                            isHeader ? 'text-cyan-400 font-bold' :
                            'text-slate-300'
                          } px-1.5 py-0.5 rounded-sm`}
                        >
                          {line}
                        </div>
                      );
                    })
                  ) : (
                    <div className="text-slate-500 py-6 text-center">
                      No diff available for this refactoring pattern.
                    </div>
                  )}
                </div>
              </div>

              {/* Verification Gating Status */}
              <div className="bg-[#121524] border border-white/5 rounded-xl p-3 flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                    {verificationStatus?.passed ? (
                      <ShieldCheck className="w-4 h-4 text-emerald-400" />
                    ) : verificationStatus && !verificationStatus.passed ? (
                      <ShieldAlert className="w-4 h-4 text-rose-400" />
                    ) : (
                      <Zap className="w-4 h-4 text-cyan-400" />
                    )}
                    Safety Verification Gate
                  </span>

                  {verificationStatus && (
                    <span 
                      data-testid="verification-status-badge"
                      className={`text-[10px] font-mono px-2 py-0.5 rounded-full font-bold uppercase ${
                        verificationStatus.passed 
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' 
                          : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                      }`}
                    >
                      {verificationStatus.passed ? 'Safe (Tests Passed)' : 'Blocked (Tests Failed)'}
                    </span>
                  )}
                </div>

                <p className="text-[11px] text-slate-400">
                  {isVerifying ? 'Running test suite in temporary sandbox copy...' :
                   verificationStatus ? verificationStatus.message :
                   'All refactors are automatically verified against existing test suites before any workspace changes are made.'}
                </p>

                {verificationStatus?.details?.test_summary && (
                  <div className="text-[10px] font-mono bg-black/30 p-2 rounded text-slate-400 border border-white/5">
                    Passed: {verificationStatus.details.test_summary.passed} • Failed: {verificationStatus.details.test_summary.failed}
                  </div>
                )}
              </div>

              {error && (
                <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}
            </div>

            {/* Dialog Footer */}
            <div className="p-4 border-t border-white/10 bg-[#191e33] flex items-center justify-end gap-2.5">
              <button
                onClick={() => setQuickFixOpen(false)}
                className="px-3.5 py-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/5 text-xs font-medium transition cursor-pointer"
              >
                Cancel
              </button>

              <button
                data-testid="apply-refactor-button"
                onClick={handleApply}
                disabled={Boolean(isVerifying || isApplying || (verificationStatus && !verificationStatus.passed))}
                className="px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white text-xs font-semibold shadow-md shadow-cyan-500/25 flex items-center gap-2 transition-all active:scale-95 disabled:opacity-50 cursor-pointer"
              >
                {isVerifying ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Verifying Tests...</span>
                  </>
                ) : isApplying ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Applying Changes...</span>
                  </>
                ) : (
                  <>
                    <Check className="w-3.5 h-3.5" />
                    <span>Apply Refactor</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
export default RefactorAssistantPanel;
