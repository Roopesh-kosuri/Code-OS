import type { ButtonHTMLAttributes, PropsWithChildren } from "react";

import { cn } from "../../lib/cn";

type ButtonProps = PropsWithChildren<ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }>;

export function Button({ children, className, variant = "ghost", ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex h-8 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-accent-600 text-white hover:bg-accent-500",
        variant === "ghost" && "text-slate-200 hover:bg-surface-700",
        variant === "danger" && "bg-danger text-white hover:brightness-110",
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
