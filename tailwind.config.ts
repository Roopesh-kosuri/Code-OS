import forms from "@tailwindcss/forms";
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Material 3 Color Tokens from mockups
        "primary-container": "#00e5ff",
        "on-secondary-fixed-variant": "#5700c9",
        "on-secondary-container": "#ddcdff",
        "surface-bright": "#3a393a",
        "surface-variant": "#353436",
        "on-tertiary-fixed-variant": "#594400",
        "surface-container-low": "#1c1b1c",
        "on-primary-container": "#00626e",
        "inverse-surface": "#e5e2e3",
        "on-error": "#690005",
        "on-error-container": "#ffdad6",
        "primary-fixed": "#9cf0ff",
        "secondary": "#d1bcff",
        "inverse-on-surface": "#313031",
        "tertiary-fixed": "#ffdf96",
        "tertiary-fixed-dim": "#f3bf26",
        "on-secondary": "#3c0090",
        "primary-fixed-dim": "#00daf3",
        "on-tertiary": "#3e2e00",
        "error-container": "#93000a",
        "surface-container-highest": "#353436",
        "outline-variant": "#3b494c",
        "secondary-fixed": "#e9ddff",
        "primary": "#c3f5ff",
        "surface": "#131314",
        "on-background": "#e5e2e3",
        "on-surface": "#e5e2e3",
        "on-surface-variant": "#bac9cc",
        "surface-dim": "#131314",
        "surface-container": "#201f20",
        "on-tertiary-fixed": "#251a00",
        "surface-container-lowest": "#0e0e0f",
        "secondary-container": "#7000ff",
        "surface-tint": "#00daf3",
        "on-secondary-fixed": "#23005b",
        "surface-container-high": "#2a2a2b",
        "on-primary-fixed": "#001f24",
        "on-primary-fixed-variant": "#004f58",
        "background": "#131314",
        "error": "#ffb4ab",
        "outline": "#849396",
        "on-primary": "#00363d",
        "on-tertiary-container": "#6f5500",
        "tertiary-container": "#fec931",
        "tertiary": "#ffeac0",
        "inverse-primary": "#006875",
        "secondary-fixed-dim": "#d1bcff",
        // Legacy colors (keep for compatibility)
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
      borderRadius: {
        DEFAULT: "0.25rem",
        lg: "0.5rem",
        xl: "0.75rem",
        full: "9999px"
      },
      spacing: {
        "container-padding": "12px",
        "panel-gap": "1px",
        "unit": "4px",
        "sidebar-width": "260px",
        "nav-rail-width": "56px"
      },
      fontFamily: {
        "headline-lg": ["Inter"],
        "headline-md": ["Inter"],
        "body-base": ["Inter"],
        "code-base": ["JetBrains Mono"],
        "label-caps": ["Inter"],
        "code-sm": ["JetBrains Mono"],
        // Legacy font names (keep for compatibility)
        sans: ["Inter", "Segoe UI", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Cascadia Code", "Consolas", "monospace"]
      },
      fontSize: {
        "headline-lg": ["24px", { "lineHeight": "32px", "letterSpacing": "-0.02em", "fontWeight": "600" }],
        "headline-md": ["18px", { "lineHeight": "24px", "letterSpacing": "-0.01em", "fontWeight": "600" }],
        "body-base": ["13px", { "lineHeight": "20px", "letterSpacing": "0", "fontWeight": "400" }],
        "code-base": ["13px", { "lineHeight": "22px", "letterSpacing": "0", "fontWeight": "450" }],
        "label-caps": ["10px", { "lineHeight": "12px", "letterSpacing": "0.08em", "fontWeight": "700" }],
        "code-sm": ["11px", { "lineHeight": "16px", "letterSpacing": "0", "fontWeight": "400" }]
      }
    }
  },
  plugins: [forms]
} satisfies Config;
