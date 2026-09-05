import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Semantic tokens — components reference these, never raw hex.
        surface: "rgb(var(--surface) / <alpha-value>)",
        elevated: "rgb(var(--elevated) / <alpha-value>)",
        sunken: "rgb(var(--sunken) / <alpha-value>)",
        border: "rgb(var(--border) / <alpha-value>)",
        ink: "rgb(var(--ink) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        faint: "rgb(var(--faint) / <alpha-value>)",
        brand: "rgb(var(--brand) / <alpha-value>)",
        "on-brand": "rgb(var(--on-brand) / <alpha-value>)",
        ok: "rgb(var(--ok) / <alpha-value>)",
        warn: "rgb(var(--warn) / <alpha-value>)",
        danger: "rgb(var(--danger) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        // A display scale that actually scales. Headline sizes are fluid so the
        // hero holds its proportions from a phone to a projector, with tracking
        // tightened as size grows — large type set at body tracking looks loose.
        hero: [
          "clamp(2.75rem, 8vw, 6.5rem)",
          { lineHeight: "0.94", letterSpacing: "-0.045em", fontWeight: "600" },
        ],
        display: [
          "clamp(2rem, 5vw, 3.5rem)",
          { lineHeight: "1.02", letterSpacing: "-0.035em", fontWeight: "600" },
        ],
        title: [
          "clamp(1.375rem, 2.6vw, 1.875rem)",
          { lineHeight: "1.15", letterSpacing: "-0.02em", fontWeight: "600" },
        ],
        lede: [
          "clamp(1rem, 1.5vw, 1.1875rem)",
          { lineHeight: "1.55", letterSpacing: "-0.01em" },
        ],
        // Small-caps nav and eyebrow labels.
        eyebrow: [
          "0.6875rem",
          { lineHeight: "1", letterSpacing: "0.14em", fontWeight: "500" },
        ],
      },
      maxWidth: {
        prose: "62ch",
      },
      boxShadow: {
        card: "var(--shadow-card)",
        lift: "var(--shadow-lift)",
      },
      transitionTimingFunction: {
        DEFAULT: "var(--ease)",
        ease: "var(--ease)",
        soft: "var(--ease-soft)",
      },
      transitionDuration: {
        DEFAULT: "var(--dur)",
        fast: "var(--dur-fast)",
        slow: "var(--dur-slow)",
      },
      keyframes: {
        rise: {
          from: { opacity: "0", transform: "translateY(14px)" },
          to: { opacity: "1", transform: "none" },
        },
        fade: {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "scale-in": {
          from: { opacity: "0", transform: "scale(0.97)" },
          to: { opacity: "1", transform: "none" },
        },
        // A quiet pulse for a value that just changed, so a number updating
        // in place is noticed without demanding attention.
        settle: {
          "0%": { backgroundColor: "rgb(var(--sunken))" },
          "100%": { backgroundColor: "transparent" },
        },
        marquee: {
          from: { transform: "translateX(0)" },
          to: { transform: "translateX(-50%)" },
        },
      },
      animation: {
        rise: "rise var(--dur-slow) var(--ease) both",
        fade: "fade var(--dur) var(--ease) both",
        "scale-in": "scale-in var(--dur) var(--ease) both",
        settle: "settle 1.2s var(--ease-soft) both",
        marquee: "marquee 38s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
