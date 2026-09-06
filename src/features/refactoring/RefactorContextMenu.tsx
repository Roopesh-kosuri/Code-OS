import React from 'react';
import { useRefactorStore } from './refactorStore';
import { 
  Wand2, 
  Scissors, 
  Tag, 
  Layers, 
  GitBranch, 
  CheckSquare 
} from 'lucide-react';

interface RefactorContextMenuProps {
  x?: number;
  y?: number;
  filePath?: string;
  selectedText?: string;
  onClose?: () => void;
  isOpen?: boolean;
}

export const RefactorContextMenu: React.FC<RefactorContextMenuProps> = ({
  x = 0,
  y = 0,
  filePath = 'src/example.py',
  selectedText = '',
  onClose,
  isOpen = true
}) => {
  const { previewRefactor } = useRefactorStore();

  if (!isOpen) return null;

  const handleAction = (refactorType: string) => {
    previewRefactor({
      type: refactorType,
      filePath,
      symbolName: selectedText ? 'extracted_func' : undefined,
      description: `Refactor ${refactorType}`
    });
    if (onClose) onClose();
  };

  return (
    <div
      role="menu"
      data-testid="refactor-context-menu"
      aria-label="Refactoring Options"
      className="fixed z-50 min-w-[200px] bg-[#1e1e2e]/95 backdrop-blur-md border border-white/10 rounded-xl shadow-2xl p-1.5 text-xs text-slate-200"
      style={{ top: y, left: x }}
    >
      <div className="px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400 border-b border-white/5 flex items-center gap-1.5">
        <Wand2 className="w-3.5 h-3.5 text-cyan-400" />
        AI Refactoring
      </div>

      <div className="py-1 space-y-0.5">
        <button
          role="menuitem"
          className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-cyan-500/20 hover:text-cyan-300 flex items-center gap-2 transition"
          onClick={() => handleAction('extract_function')}
        >
          <Scissors className="w-3.5 h-3.5 text-cyan-400" />
          <span>Extract Function</span>
        </button>

        <button
          role="menuitem"
          className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-cyan-500/20 hover:text-cyan-300 flex items-center gap-2 transition"
          onClick={() => handleAction('rename_symbol')}
        >
          <Tag className="w-3.5 h-3.5 text-amber-400" />
          <span>Rename Symbol</span>
        </button>

        <button
          role="menuitem"
          className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-cyan-500/20 hover:text-cyan-300 flex items-center gap-2 transition"
          onClick={() => handleAction('apply_strategy_pattern')}
        >
          <Layers className="w-3.5 h-3.5 text-purple-400" />
          <span>Apply Strategy Pattern</span>
        </button>

        <button
          role="menuitem"
          className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-cyan-500/20 hover:text-cyan-300 flex items-center gap-2 transition"
          onClick={() => handleAction('flatten_conditionals')}
        >
          <GitBranch className="w-3.5 h-3.5 text-emerald-400" />
          <span>Flatten Conditionals</span>
        </button>

        <button
          role="menuitem"
          className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-cyan-500/20 hover:text-cyan-300 flex items-center gap-2 transition border-t border-white/5"
          onClick={() => handleAction('quick_fix')}
        >
          <CheckSquare className="w-3.5 h-3.5 text-pink-400" />
          <span>Quick Fix Code Smell</span>
        </button>
      </div>
    </div>
  );
};
