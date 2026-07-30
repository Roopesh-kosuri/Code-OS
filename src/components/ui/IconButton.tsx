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
      className={cn("grid h-8 w-8 place-items-center rounded-full text-on-surface-variant transition-all duration-200 hover:bg-surface-variant/50 hover:text-primary active:scale-95", className)}
      {...props}
    >
      {icon}
    </button>
  );
}
