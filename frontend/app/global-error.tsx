"use client";

/**
 * Last-resort boundary for errors thrown in the root layout itself.
 *
 * It must render its own <html> and <body>: at this point the normal layout is
 * what failed, so nothing above this component is available.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          fontFamily: "ui-sans-serif, system-ui, sans-serif",
          padding: "3rem 1.5rem",
          maxWidth: "40rem",
          margin: "0 auto",
          lineHeight: 1.6,
        }}
      >
        <h1 style={{ fontSize: "1.125rem", fontWeight: 600 }}>
          AutoBuy failed to load
        </h1>
        <p style={{ marginTop: "0.5rem", opacity: 0.75 }}>
          Nothing was charged. Money actions are recorded server-side, so the
          merchant dashboard remains authoritative.
        </p>
        {error.digest ? (
          <p style={{ marginTop: "0.5rem", fontFamily: "monospace", fontSize: "0.75rem", opacity: 0.6 }}>
            digest: {error.digest}
          </p>
        ) : null}
        <button
          onClick={reset}
          style={{
            marginTop: "1.25rem",
            padding: "0.5rem 1rem",
            borderRadius: "0.5rem",
            border: "1px solid currentColor",
            background: "transparent",
            cursor: "pointer",
            font: "inherit",
          }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}
