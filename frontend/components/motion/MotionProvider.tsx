"use client";

import { useEffect } from "react";

/**
 * Marks the document motion-ready once React has hydrated.
 *
 * Everything animated keys off `html[data-motion="on"]`, which only appears
 * here. Before hydration the page renders in its final, visible state — so a
 * failed or slow bundle produces a plain page rather than an empty one.
 */
export function MotionProvider() {
  useEffect(() => {
    document.documentElement.dataset.motion = "on";
  }, []);

  return null;
}
