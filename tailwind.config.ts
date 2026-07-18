import forms from "@tailwindcss/forms";
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          950: "var(--bg-surface-950)",
          900: "var(--bg-surface-900)",
          850: "var(--bg-surface-850)",
          800: "var(--bg-surface-800)",
          700: "var(--bg-surface-700)"
        },
        slate: {
          100: "var(--text-100)",
          200: "var(--text-200)",
          300: "var(--text-300)",
          400: "var(--text-400)",
          500: "var(--text-500)"
        },
        accent: {
          500: "var(--accent-500)",
          600: "var(--accent-600)"
        },
        success: "var(--success)",
        warning: "var(--warning)",
        danger: "var(--danger)"
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Cascadia Code", "Consolas", "monospace"]
      }
    }
  },
  plugins: [forms]
} satisfies Config;
