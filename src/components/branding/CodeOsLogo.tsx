import { Terminal, Sparkles } from "lucide-react";

type CodeOsLogoProps = {
  imageClassName?: string;
  className?: string;
  priority?: boolean;
};

export function CodeOsLogo({ className = "" }: CodeOsLogoProps) {
  return (
    <div className={`inline-flex items-center gap-3.5 px-5 py-3 rounded-xl bg-gradient-to-r from-surface-950 via-surface-900 to-surface-950 border border-cyan-500/30 shadow-xl shadow-cyan-950/40 backdrop-blur-md select-none ${className}`}>
      <div className="relative flex items-center justify-center w-10 h-10 rounded-lg bg-gradient-to-br from-cyan-400 via-accent-500 to-indigo-600 shadow-md shadow-cyan-500/30 ring-1 ring-white/20">
        <Terminal className="w-5.5 h-5.5 text-surface-950 font-bold stroke-[2.5]" />
        <Sparkles className="w-3.5 h-3.5 text-amber-300 absolute -top-1 -right-1 animate-pulse drop-shadow-sm" />
      </div>
      <div className="flex flex-col text-left">
        <span className="text-xl font-black tracking-wider text-white font-mono flex items-center">
          CODE<span className="text-cyan-400 font-extrabold ml-1">OS</span>
        </span>
        <span className="text-[9px] uppercase tracking-widest font-bold text-cyan-400/80 -mt-0.5">
          Local AI Development Engine
        </span>
      </div>
    </div>
  );
}
