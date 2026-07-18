import { useEffect, useState, useRef } from "react";
import { ChevronRight, X } from "lucide-react";
import { CodeOsLogo } from "../branding/CodeOsLogo";
import { Button } from "../ui/Button";

type Step = {
  targetId?: string;
  title: string;
  description: string;
  placement: "center" | "right" | "left" | "top" | "bottom";
};

const WALKTHROUGH_STEPS: Step[] = [
  {
    title: "Welcome",
    description: "Your local-first AI development workspace. Let's take a quick tour to get you situated.",
    placement: "center"
  },
  {
    targetId: "btn-open-folder",
    title: "Workspace Folder Explorer",
    description: "Start here by opening a local folder. The workspace scanner indexes files, imports, and AST declarations.",
    placement: "bottom"
  },
  {
    targetId: "activity-btn-explorer",
    title: "File Explorer",
    description: "Browse files, create folders, and manage workspace directory assets natively.",
    placement: "right"
  },
  {
    targetId: "activity-btn-search",
    title: "Global Search",
    description: "Perform fast plain text or regex searches across the entire workspace directory.",
    placement: "right"
  },
  {
    targetId: "activity-btn-git",
    title: "Source Control (Git)",
    description: "Track modifications, stage files, write commit messages, and sync with remotes.",
    placement: "right"
  },
  {
    targetId: "activity-btn-agent",
    title: "Autonomous Agent Console",
    description: "Orchestrate specialized AI agents (Planner, Coder, Reviewer, Tester) in a DAG to execute engineering workflows.",
    placement: "right"
  },
  {
    targetId: "activity-btn-duo",
    title: "Duo Loop Automation",
    description: "Run generator and critic AI validation loops to automatically iterate and test solutions.",
    placement: "right"
  },
  {
    targetId: "activity-btn-diagnostics",
    title: "Diagnostics & Health",
    description: "Monitor parser state, index logs, system resource usage, and background service health.",
    placement: "right"
  },
  {
    targetId: "activity-btn-memory",
    title: "AI Memory store",
    description: "Review and manage shared memories, project guidelines, and style rules retained by agents.",
    placement: "right"
  },
  {
    targetId: "activity-btn-context",
    title: "AI Context Manager",
    description: "Inspect active context variables, index configurations, and tokens currently cached.",
    placement: "right"
  },
  {
    targetId: "activity-btn-diff",
    title: "AI Proposals Inspector",
    description: "Review all AI code proposals in a side-by-side diff viewer before applying to files.",
    placement: "right"
  },
  {
    targetId: "activity-btn-terminal",
    title: "Native PTY Terminals",
    description: "Access fully interactive local shells mapped to the workspace directory.",
    placement: "right"
  },
  {
    targetId: "activity-btn-aichat",
    title: "Integrated AI Chat Panel",
    description: "Converse with models, attach codebase references, and ask programming questions directly.",
    placement: "right"
  },
  {
    targetId: "btn-trust-status",
    title: "Workspace Security Trust Guardrail",
    description: "Toggle security boundaries here. Restricted mode protects your files by disabling write permissions.",
    placement: "bottom"
  },
  {
    targetId: "activity-btn-settings",
    title: "Configuration Hub",
    description: "Manage settings, configure custom MCP servers, add API keys, or reset trust decisions at any time.",
    placement: "right"
  }
];

type OnboardingWizardProps = {
  onClose: () => void;
};

export function OnboardingWizard({ onClose }: OnboardingWizardProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [optInTutorial, setOptInTutorial] = useState(false);
  const [spotlightRect, setSpotlightRect] = useState<DOMRect | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [tooltipStyle, setTooltipStyle] = useState<React.CSSProperties>({});

  const step = WALKTHROUGH_STEPS[currentStep];

  // Trigger active layout adjustments and pane shifts dynamically
  useEffect(() => {
    const targetId = step.targetId;
    if (!targetId) return;

    if (targetId.startsWith("activity-btn-")) {
      const utility = targetId.substring("activity-btn-".length);
      if (utility === "terminal") {
        if (!document.getElementById("terminal-panel")) {
          window.dispatchEvent(new CustomEvent("code-os:menu", { detail: "view.toggleTerminal" }));
        }
      } else if (utility === "aichat") {
        if (!document.getElementById("ai-chat-panel")) {
          window.dispatchEvent(new CustomEvent("code-os:menu", { detail: "view.toggleAI" }));
        }
      } else if (utility === "settings") {
        document.getElementById("activity-btn-settings")?.click();
      } else {
        window.dispatchEvent(new CustomEvent("code-os:switch-utility", { detail: utility }));
      }
    }

    // Cleanup: close modal overlay when transitioning away from Settings
    return () => {
      if (targetId === "activity-btn-settings") {
        window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
      }
    };
  }, [currentStep, step]);

  // Recalculate spotlight position and tooltip coordinates dynamically
  useEffect(() => {
    const targetId = step.targetId;

    const updatePosition = () => {
      const el = targetId ? document.getElementById(targetId) : null;
      if (!targetId || !el) {
        setSpotlightRect(null);
        setTooltipStyle({
          left: `${window.innerWidth / 2}px`,
          top: `${window.innerHeight / 2}px`,
          transform: "translate(-50%, -50%)"
        });
        return;
      }

      const rect = el.getBoundingClientRect();
      // Update spotlight rectangle dimensions
      setSpotlightRect((prev) => {
        if (
          prev &&
          prev.left === rect.left &&
          prev.top === rect.top &&
          prev.width === rect.width &&
          prev.height === rect.height
        ) {
          return prev;
        }
        return rect;
      });

      const gap = 12;
      let left = 0;
      let top = 0;
      let transform = "";
      const tooltipWidth = 320;

      if (step.placement === "right") {
        left = rect.right + gap;
        top = rect.top + rect.height / 2;
        transform = "translateY(-50%)";
      } else if (step.placement === "bottom") {
        left = rect.left + rect.width / 2;
        top = rect.bottom + gap;
        transform = "translateX(-50%)";
      } else if (step.placement === "top") {
        left = rect.left + rect.width / 2;
        top = rect.top - gap;
        transform = "translate(-50%, -100%)";
      } else if (step.placement === "left") {
        left = rect.left - gap;
        top = rect.top + rect.height / 2;
        transform = "translate(-100%, -50%)";
      }

      // Safeguard against boundary overflow (so tooltip never runs off-screen)
      if (step.placement === "right" || step.placement === "left") {
        if (left < 12) left = 12;
        if (left + tooltipWidth > window.innerWidth - 12) {
          left = window.innerWidth - tooltipWidth - 12;
        }
      } else {
        const expectedLeft = left - tooltipWidth / 2;
        if (expectedLeft < 12) {
          left = 12 + tooltipWidth / 2;
        } else if (expectedLeft + tooltipWidth > window.innerWidth - 12) {
          left = window.innerWidth - tooltipWidth / 2 - 12;
        }
      }

      setTooltipStyle({
        left: `${left}px`,
        top: `${top}px`,
        transform
      });
    };

    updatePosition();

    const interval = setInterval(updatePosition, 100);
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);

    return () => {
      clearInterval(interval);
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [currentStep, step]);

  const handleNext = () => {
    if (currentStep === 0) {
      if (!acceptedTerms) return;
      if (!optInTutorial) {
        localStorage.setItem("code-os:onboarding-complete", "true");
        onClose();
        setTimeout(() => {
          window.dispatchEvent(new CustomEvent("code-os:menu", { detail: "file.openFolder" }));
        }, 100);
        return;
      }
    }
    if (currentStep < WALKTHROUGH_STEPS.length - 1) {
      setCurrentStep((prev) => prev + 1);
    } else {
      localStorage.setItem("code-os:onboarding-complete", "true");
      onClose();
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent("code-os:menu", { detail: "file.openFolder" }));
      }, 100);
    }
  };

  const handleSkip = () => {
    localStorage.setItem("code-os:onboarding-complete", "true");
    onClose();
  };

  return (
    <div className="fixed inset-0 z-90 overflow-hidden font-sans select-none">
      {/* Background Dimmed Overlay */}
      <div className="absolute inset-0 bg-black/75 backdrop-blur-[2px] transition-all duration-300" />

      {/* Spotlight highlight box */}
      {spotlightRect && (
        <div
          className="absolute border-2 border-accent-500 rounded-lg shadow-[0_0_0_9999px_rgba(0,0,0,0.65)] transition-all duration-300 z-91 pointer-events-none"
          style={{
            left: `${spotlightRect.left - 4}px`,
            top: `${spotlightRect.top - 4}px`,
            width: `${spotlightRect.width + 8}px`,
            height: `${spotlightRect.height + 8}px`
          }}
        />
      )}

      {/* Onboarding Dialog */}
      {currentStep === 0 ? (
        /* Welcome & Terms Modal (Center screen) */
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-surface-900 border border-surface-700/80 rounded-xl w-full max-w-md p-6 shadow-2xl z-95 space-y-4">
          <div className="flex flex-col items-center gap-3 text-center">
            <CodeOsLogo className="w-full max-w-[340px] px-5 py-3" imageClassName="h-14 w-full" priority />
            <div>
              <h2 className="text-lg font-bold text-white leading-tight">Welcome</h2>
              <p className="text-xs text-slate-400">Local-First AI Development Shell</p>
            </div>
          </div>

          <div className="space-y-2 text-xs text-slate-350 leading-relaxed">
            <p>
              Automated pair-programming, terminals, and workspace indexers run entirely on your machine.
            </p>
            <p className="text-amber-400 font-semibold bg-amber-950/30 border border-amber-900/30 p-2 rounded-md">
              ⚠️ DISCLAIMER: Any lost code lines, file deletions, or system changes resulting from local AI execution will not be our responsibility, as this is a fully local execution model running on your hardware. Always commit your code.
            </p>
          </div>

          <div className="bg-surface-950 border border-surface-800 rounded-lg p-3 space-y-2 max-h-36 overflow-y-auto">
            <h4 className="text-[10px] uppercase font-bold text-slate-500">Execution Terms</h4>
            <ul className="space-y-1.5 text-[10px] text-slate-450 leading-relaxed">
              <li className="flex gap-1.5">
                <span className="text-accent-500 font-bold">1.</span>
                <span>All code edits, index mappings, and chat weights run 100% locally.</span>
              </li>
              <li className="flex gap-1.5">
                <span className="text-accent-500 font-bold">2.</span>
                <span>Autonomous agents require explicit action approval before altering files or executing terminal shells.</span>
              </li>
              <li className="flex gap-1.5">
                <span className="text-accent-500 font-bold">3.</span>
                <span>Restricted mode is enabled by default for unverified or external workspace directories.</span>
              </li>
            </ul>
          </div>

          {/* Terms Checkbox */}
          <div className="flex flex-col gap-3">
            <label className="flex items-start gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={acceptedTerms}
                onChange={(e) => setAcceptedTerms(e.target.checked)}
                className="mt-0.5 rounded text-accent-500 focus:ring-accent-500 bg-surface-950 border-surface-700 h-4 w-4"
              />
              <span className="text-xs text-slate-300 leading-normal">
                I agree to the Local Data Isolation &amp; Execution parameters.
              </span>
            </label>
            <label className="flex items-start gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={optInTutorial}
                onChange={(e) => setOptInTutorial(e.target.checked)}
                disabled={!acceptedTerms}
                className="mt-0.5 rounded text-accent-500 focus:ring-accent-500 bg-surface-950 border-surface-700 h-4 w-4 disabled:opacity-50"
              />
              <span className={`text-xs leading-normal ${acceptedTerms ? 'text-slate-300' : 'text-slate-500'}`}>
                Show me a guided tutorial of the workspace.
              </span>
            </label>
          </div>

          <div className="flex justify-between items-center pt-2 border-t border-surface-800">
            <button onClick={handleSkip} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">
              Skip Intro
            </button>
            <Button
              variant="primary"
              disabled={!acceptedTerms}
              onClick={handleNext}
              className="px-4 py-1.5 text-xs bg-accent-600 hover:bg-accent-500"
            >
              {optInTutorial ? "Start Walkthrough" : "Ready to Code?"} <ChevronRight size={13} className="ml-1" />
            </Button>
          </div>
        </div>
      ) : (
        /* Walkthrough Tooltip Overlay */
        <div
          ref={tooltipRef}
          style={tooltipStyle}
          className="absolute bg-surface-900 border border-surface-700/80 rounded-xl w-80 p-4 shadow-2xl z-95 space-y-3"
        >
          <div className="flex justify-between items-start">
            <span className="text-[10px] font-bold text-accent-400 uppercase tracking-widest">
              Step {currentStep} of {WALKTHROUGH_STEPS.length - 1}
            </span>
            <button onClick={handleSkip} className="text-slate-500 hover:text-white transition-colors">
              <X size={14} />
            </button>
          </div>

          <div>
            <h3 className="text-sm font-bold text-white mb-1 leading-snug">{step.title}</h3>
            <p className="text-xs text-slate-350 leading-relaxed">{step.description}</p>
          </div>

          <div className="flex justify-between items-center pt-2 border-t border-surface-800">
            <button onClick={handleSkip} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">
              Skip
            </button>
            <Button
              variant="primary"
              onClick={handleNext}
              className="px-3.5 py-1 text-xs bg-accent-600 hover:bg-accent-500 h-7"
            >
              {currentStep === WALKTHROUGH_STEPS.length - 1 ? "Ready to Code?" : "Next"} <ChevronRight size={12} className="ml-0.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
