import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "../../lib/cn";

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  icon: ReactNode;
};

export function IconButton({ label, icon, className, ...props }: IconButtonProps) {
  return (
    <button
      aria-label={label}
      title={label}
      className={cn("grid h-8 w-8 place-items-center rounded-md text-slate-300 transition-colors hover:bg-surface-700 hover:text-white", className)}
      {...props}
    >
      {icon}
    </button>
  );
}
