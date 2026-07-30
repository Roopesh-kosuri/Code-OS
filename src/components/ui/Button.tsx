import type { ButtonHTMLAttributes, PropsWithChildren } from "react";

import { cn } from "../../lib/cn";

type ButtonProps = PropsWithChildren<ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger" }>;

export function Button({ children, className, variant = "ghost", ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex h-8 items-center justify-center gap-2 rounded-lg px-3.5 text-body-base font-body-base font-semibold tracking-wide transition-all duration-200 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-primary-container text-on-primary-container hover:brightness-110 shadow-[inset_0_0_8px_rgba(0,218,243,0.2)] shadow-primary-container/20",
        variant === "secondary" && "bg-surface-variant/60 border border-outline-variant/30 text-on-surface hover:bg-surface-variant/90 hover:text-on-surface",
        variant === "ghost" && "text-on-surface-variant hover:bg-surface-variant/40 hover:text-on-surface",
        variant === "danger" && "bg-error/20 border border-error/40 text-error hover:bg-error/30",
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
