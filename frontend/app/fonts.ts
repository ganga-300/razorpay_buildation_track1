import { Instrument_Sans, JetBrains_Mono } from "next/font/google";

/**
 * One grotesk carries the whole interface.
 *
 * Hierarchy comes from weight and scale rather than from a second family —
 * mixing typefaces to create contrast usually reads as indecision. Instrument
 * Sans has enough character at display sizes to feel authored, and stays quiet
 * at 13px where most of this interface lives.
 */
export const sans = Instrument_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
  weight: ["400", "500", "600", "700"],
});

/**
 * Order ids, product ids and payment signatures are read character by
 * character. A mono with disambiguated 0/O and 1/l is not a stylistic choice
 * here — it is what makes `ord-81b5ed36fad1` legible.
 */
export const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
  weight: ["400", "500"],
});
