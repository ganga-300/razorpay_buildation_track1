/**
 * Server-Sent Events client for `POST /chat`.
 *
 * The browser's native `EventSource` only issues GET requests with no body, so
 * it cannot be used here. This reads the `fetch` response stream directly and
 * parses the SSE wire format, which also lets us surface HTTP-level failures
 * (a 422, a dead backend) as ordinary errors before the stream begins.
 */

import { API_BASE_URL } from "./api";
import type { ChatEvent } from "./types";

/**
 * Frames are separated by a blank line, but the line terminator is not fixed:
 * the SSE spec allows LF, CRLF, or CR, and `sse-starlette` emits CRLF. Matching
 * only "\n\n" silently buffers the entire stream and then fails to parse the
 * concatenated result, so the boundary is matched with a pattern.
 */
const FRAME_BOUNDARY = /\r?\n\r?\n/;

/** Split a raw SSE frame into its event name and JSON data. */
function parseFrame(frame: string): ChatEvent | null {
  let name = "message";
  const dataLines: string[] = [];

  for (const rawLine of frame.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (line.startsWith(":")) continue; // comment / keep-alive
    if (line.startsWith("event:")) {
      name = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  const payload = dataLines.join("\n");
  if (!payload) return null;

  try {
    return { event: name, data: JSON.parse(payload) } as ChatEvent;
  } catch {
    // A malformed frame must not abort a turn that is otherwise working.
    console.warn("Discarding unparseable SSE frame", { name, payload });
    return null;
  }
}

export interface StreamChatOptions {
  message: string;
  conversationId?: string | null;
  signal?: AbortSignal;
}

/**
 * Send a message and yield agent events as they arrive.
 *
 * @throws Error if the request fails before the stream opens.
 */
export async function* streamChat({
  message,
  conversationId,
  signal,
}: StreamChatOptions): AsyncGenerator<ChatEvent> {
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({
      message,
      conversation_id: conversationId ?? null,
    }),
    signal,
  });

  if (!response.ok || !response.body) {
    const detail = await response.text().catch(() => "");
    throw new Error(
      `Chat request failed (${response.status})${detail ? `: ${detail}` : ""}`,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // A chunk can end mid-frame, so the trailing partial stays in the
      // buffer until more bytes arrive.
      let match = FRAME_BOUNDARY.exec(buffer);
      while (match !== null) {
        const frame = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);

        const parsed = parseFrame(frame);
        if (parsed) yield parsed;

        match = FRAME_BOUNDARY.exec(buffer);
      }
    }

    // Flush anything the server sent without a trailing blank line.
    const tail = parseFrame(buffer);
    if (tail) yield tail;
  } finally {
    reader.releaseLock();
  }
}
