import type { Config } from "tailwindcss";

/**
 * Design tokens mirror the Figma variables in "Magnitude — UI/UX".
 * Change a value in Figma -> change it here (Phase 2 adds a sync check).
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./hooks/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: { base: "#0A0C10", surface: "#11141B", raised: "#181C26" },
        line: { subtle: "#232837", strong: "#323951" },
        ink: { primary: "#ECEEF3", secondary: "#9AA1B4", tertiary: "#5F667A", onAccent: "#06140F" },
        accent: { DEFAULT: "#7CF5C0", dim: "#0F2A22" },
        correct: { DEFAULT: "#7CF5C0", dim: "#0F2A22" },
        wrong: { DEFAULT: "#FF7A8A", dim: "#2E1519" },
        gold: "#F7C85A",
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      borderRadius: { card: "20px", control: "12px", key: "8px" },
      boxShadow: { glow: "0 0 56px rgba(124, 245, 192, 0.22)" },
      keyframes: {
        timer: { from: { width: "100%" }, to: { width: "0%" } },
        shake: {
          "0%, 100%": { transform: "translateX(0)" },
          "20%": { transform: "translateX(-6px)" },
          "40%": { transform: "translateX(6px)" },
          "60%": { transform: "translateX(-4px)" },
          "80%": { transform: "translateX(4px)" },
        },
        rise: {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        timer: "timer linear forwards",
        rise: "rise 180ms ease-out both",
        shake: "shake 280ms ease-in-out both",
      },
    },
  },
  plugins: [],
};

export default config;
