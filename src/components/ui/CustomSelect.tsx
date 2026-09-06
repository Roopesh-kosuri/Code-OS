import React, { useState, useRef, useEffect } from "react";
import { ChevronDown, Check, type LucideIcon } from "lucide-react";

export interface CustomSelectOption {
  value: string;
  label: string;
  icon?: LucideIcon;
  iconColor?: string;
  badge?: string;
  badgeColor?: string;
  description?: string;
}

interface CustomSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: CustomSelectOption[];
  disabled?: boolean;
  placeholder?: string;
  className?: string;
  align?: "left" | "right";
  variant?: "default" | "liquid-glass";
}

export const CustomSelect: React.FC<CustomSelectProps> = ({
  value,
  onChange,
  options,
  disabled = false,
  placeholder = "Select an option",
  className = "",
  align = "left",
  variant = "default",
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const selectedOption = options.find((opt) => opt.value === value);

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener("mousedown", handleOutsideClick);
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  const SelectedIcon = selectedOption?.icon;

  if (variant === "liquid-glass") {
    return (
      <div className={`relative inline-block w-full ${className}`} ref={dropdownRef}>
        {/* Trigger Button Matching LiquidGlassModelSelector */}
        <button
          type="button"
          disabled={disabled}
          onClick={() => setIsOpen((prev) => !prev)}
          className={`w-full text-left rounded-lg border transition-all duration-150 flex items-center justify-between gap-2.5 cursor-pointer shadow-sm group px-3 py-2 ${
            disabled
              ? "opacity-50 cursor-not-allowed bg-[#131622]/40 border-white/5"
              : isOpen
                ? "bg-[#181b29] border-primary/60 ring-1 ring-primary/30 shadow-[0_0_16px_rgba(0,218,243,0.2)]"
                : "bg-[#131622]/90 hover:bg-[#191c2c] border-white/10 hover:border-white/25 hover:shadow-[0_2px_8px_rgba(0,0,0,0.4)]"
          }`}
        >
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            <div className="p-1.5 rounded-md bg-primary/10 border border-primary/20 text-primary shrink-0">
              {SelectedIcon ? (
                <SelectedIcon size={14} className={selectedOption?.iconColor || "text-primary"} />
              ) : (
                <Check size={14} className="text-primary" />
              )}
            </div>
            <div className="flex flex-col min-w-0 flex-1">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="font-semibold text-xs text-white truncate group-hover:text-primary transition-colors">
                  {selectedOption ? selectedOption.label : placeholder}
                </span>
                {selectedOption?.badge && (
                  <span
                    className={`text-[9px] px-1.5 py-0.2 rounded-full font-mono font-medium border shrink-0 ${
                      selectedOption.badgeColor || "bg-primary/15 text-primary border-primary/30"
                    }`}
                  >
                    {selectedOption.badge}
                  </span>
                )}
              </div>
              <span className="text-[10px] text-on-surface-variant/70 font-mono truncate">
                {selectedOption?.description || selectedOption?.value || "Provider"}
              </span>
            </div>
          </div>

          <ChevronDown
            size={13}
            className={`text-on-surface-variant shrink-0 ml-1 transition-transform duration-200 ${
              isOpen ? "rotate-180 text-primary" : "group-hover:text-white"
            }`}
          />
        </button>

        {/* Floating Glassmorphic Dropdown Menu */}
        {isOpen && (
          <div
            className={`absolute ${align === "right" ? "right-0" : "left-0"} top-full mt-1.5 w-full min-w-[240px] max-h-[300px] overflow-y-auto liquid-glass-popover rounded-xl shadow-2xl p-1.5 z-50 animate-popover-in custom-scrollbar`}
          >
            <div className="space-y-0.5">
              {options.map((opt) => {
                const isSelected = opt.value === value;
                const OptIcon = opt.icon;

                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => {
                      onChange(opt.value);
                      setIsOpen(false);
                    }}
                    className={`w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-lg text-xs transition-all text-left cursor-pointer liquid-glass-item ${
                      isSelected
                        ? "bg-primary/20 text-white font-bold border border-primary/40 shadow-[0_0_12px_rgba(0,218,243,0.15)]"
                        : "text-on-surface hover:text-white"
                    }`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      {OptIcon && (
                        <div className="p-1 rounded bg-primary/10 border border-primary/20 shrink-0">
                          <OptIcon size={13} className={opt.iconColor || "text-primary"} />
                        </div>
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate font-semibold text-white">{opt.label}</span>
                          {opt.badge && (
                            <span
                              className={`text-[9px] px-1.5 py-0.2 rounded-full font-mono font-medium border ${
                                opt.badgeColor || "bg-primary/15 text-primary border-primary/30"
                              }`}
                            >
                              {opt.badge}
                            </span>
                          )}
                        </div>
                        {opt.description && (
                          <p className="text-[10px] text-on-surface-variant/70 font-mono truncate">{opt.description}</p>
                        )}
                      </div>
                    </div>

                    {isSelected && (
                      <Check size={13} className="shrink-0 text-primary animate-in zoom-in-50 ml-1.5" />
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`relative inline-block w-full ${className}`} ref={dropdownRef}>
      {/* Trigger Button */}
      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen((prev) => !prev)}
        className={`w-full flex items-center justify-between gap-2 bg-[#131315] hover:bg-[#18191d] border ${
          isOpen ? "border-primary/60 ring-2 ring-primary/20 shadow-[0_0_15px_rgba(0,229,255,0.15)]" : "border-white/10 hover:border-white/20"
        } rounded-lg px-3 py-2 text-xs text-on-surface transition-all duration-150 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed`}
      >
        <div className="flex items-center gap-2 min-w-0">
          {SelectedIcon && (
            <SelectedIcon className={`w-3.5 h-3.5 shrink-0 ${selectedOption.iconColor || "text-primary"}`} />
          )}
          <span className="truncate font-medium text-on-surface">
            {selectedOption ? selectedOption.label : placeholder}
          </span>
          {selectedOption?.badge && (
            <span className={`text-[10px] px-1.5 py-0.2 rounded font-mono ${selectedOption.badgeColor || "bg-primary/10 text-primary border border-primary/20"}`}>
              {selectedOption.badge}
            </span>
          )}
        </div>
        <ChevronDown
          size={14}
          className={`shrink-0 text-on-surface-variant transition-transform duration-200 ${
            isOpen ? "rotate-180 text-primary" : ""
          }`}
        />
      </button>

      {/* Floating Glassmorphic Dropdown Menu */}
      {isOpen && (
        <div
          className={`absolute ${align === "right" ? "right-0" : "left-0"} top-full mt-1.5 w-full min-w-[220px] max-h-[300px] overflow-y-auto bg-[#16171b]/98 backdrop-blur-xl border border-white/15 rounded-xl shadow-[0_10px_30px_rgba(0,0,0,0.6)] p-1.5 z-50 animate-in fade-in zoom-in-95 duration-150 custom-scrollbar`}
        >
          <div className="space-y-0.5">
            {options.map((opt) => {
              const isSelected = opt.value === value;
              const OptIcon = opt.icon;

              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => {
                    onChange(opt.value);
                    setIsOpen(false);
                  }}
                  className={`w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-lg text-xs transition-all text-left cursor-pointer ${
                    isSelected
                      ? "bg-primary/15 text-primary border border-primary/30 font-medium"
                      : "text-on-surface/90 hover:bg-white/[0.08] hover:text-white border border-transparent"
                  }`}
                >
                  <div className="flex items-center gap-2 min-w-0 flex-1">
                    {OptIcon && (
                      <OptIcon className={`w-3.5 h-3.5 shrink-0 ${isSelected ? "text-primary" : opt.iconColor || "text-on-surface-variant"}`} />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate">{opt.label}</span>
                        {opt.badge && (
                          <span className={`text-[9px] px-1 py-0.2 rounded font-mono ${opt.badgeColor || "bg-white/10 text-white/70"}`}>
                            {opt.badge}
                          </span>
                        )}
                      </div>
                      {opt.description && (
                        <p className="text-[10px] text-on-surface-variant truncate">{opt.description}</p>
                      )}
                    </div>
                  </div>

                  {isSelected && (
                    <Check size={13} className="shrink-0 text-primary animate-in zoom-in-50" />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

