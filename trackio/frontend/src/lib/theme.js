export const themes = {
  default: {
    "--bg-primary": "#ffffff",
    "--bg-secondary": "#f9fafb",
    "--bg-tertiary": "#f3f4f6",
    "--bg-sidebar": "#ffffff",
    "--text-primary": "#111827",
    "--text-secondary": "#6b7280",
    "--text-muted": "#9ca3af",
    "--border-color": "#e5e7eb",
    "--border-light": "#f3f4f6",
    "--accent-color": "#f97316",
    "--accent-hover": "#ea580c",
    "--accent-light": "#fff7ed",
    "--success-color": "#10b981",
    "--error-color": "#ef4444",
    "--warning-color": "#f59e0b",
    "--info-color": "#3b82f6",
    "--input-bg": "#ffffff",
    "--input-border": "#d1d5db",
    "--input-focus": "#f97316",
    "--shadow-sm": "0 1px 2px rgba(0,0,0,0.05)",
    "--shadow-md": "0 4px 6px -1px rgba(0,0,0,0.1)",
    "--radius-sm": "6px",
    "--radius-md": "8px",
    "--radius-lg": "12px",
  },
  dark: {
    "--bg-primary": "#111827",
    "--bg-secondary": "#1f2937",
    "--bg-tertiary": "#374151",
    "--bg-sidebar": "#1f2937",
    "--text-primary": "#f9fafb",
    "--text-secondary": "#d1d5db",
    "--text-muted": "#9ca3af",
    "--border-color": "#374151",
    "--border-light": "#1f2937",
    "--accent-color": "#f97316",
    "--accent-hover": "#fb923c",
    "--accent-light": "#1c1917",
    "--success-color": "#34d399",
    "--error-color": "#f87171",
    "--warning-color": "#fbbf24",
    "--info-color": "#60a5fa",
    "--input-bg": "#374151",
    "--input-border": "#4b5563",
    "--input-focus": "#f97316",
    "--shadow-sm": "0 1px 2px rgba(0,0,0,0.3)",
    "--shadow-md": "0 4px 6px -1px rgba(0,0,0,0.4)",
    "--radius-sm": "6px",
    "--radius-md": "8px",
    "--radius-lg": "12px",
  },
  soft: {
    "--bg-primary": "#fefefe",
    "--bg-secondary": "#f8f9fc",
    "--bg-tertiary": "#eef1f6",
    "--bg-sidebar": "#f8f9fc",
    "--text-primary": "#2d3748",
    "--text-secondary": "#718096",
    "--text-muted": "#a0aec0",
    "--border-color": "#e2e8f0",
    "--border-light": "#edf2f7",
    "--accent-color": "#6366f1",
    "--accent-hover": "#4f46e5",
    "--accent-light": "#eef2ff",
    "--success-color": "#10b981",
    "--error-color": "#ef4444",
    "--warning-color": "#f59e0b",
    "--info-color": "#3b82f6",
    "--input-bg": "#ffffff",
    "--input-border": "#cbd5e0",
    "--input-focus": "#6366f1",
    "--shadow-sm": "0 1px 3px rgba(0,0,0,0.04)",
    "--shadow-md": "0 4px 6px -1px rgba(0,0,0,0.06)",
    "--radius-sm": "8px",
    "--radius-md": "10px",
    "--radius-lg": "16px",
  },
  citrus: {
    "--bg-primary": "#fffef5",
    "--bg-secondary": "#fefce8",
    "--bg-tertiary": "#fef9c3",
    "--bg-sidebar": "#fefce8",
    "--text-primary": "#1c1917",
    "--text-secondary": "#57534e",
    "--text-muted": "#a8a29e",
    "--border-color": "#e7e5e4",
    "--border-light": "#f5f5f4",
    "--accent-color": "#65a30d",
    "--accent-hover": "#4d7c0f",
    "--accent-light": "#f7fee7",
    "--success-color": "#22c55e",
    "--error-color": "#ef4444",
    "--warning-color": "#eab308",
    "--info-color": "#0ea5e9",
    "--input-bg": "#ffffff",
    "--input-border": "#d6d3d1",
    "--input-focus": "#65a30d",
    "--shadow-sm": "0 1px 2px rgba(0,0,0,0.05)",
    "--shadow-md": "0 4px 6px -1px rgba(0,0,0,0.1)",
    "--radius-sm": "6px",
    "--radius-md": "8px",
    "--radius-lg": "12px",
  },
};

export function applyTheme(themeName) {
  const vars = themes[themeName] || themes.default;
  const root = document.documentElement;
  Object.entries(vars).forEach(([key, value]) => {
    root.style.setProperty(key, value);
  });
}

export function detectSystemTheme() {
  if (
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  ) {
    return "dark";
  }
  return "default";
}
