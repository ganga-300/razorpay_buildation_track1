import { describe, expect, it, vi, afterEach } from "vitest";

import { streamChat } from "./sse";

/** Build a fetch response whose body streams the given chunks verbatim. */
function mockFetchStreaming(chunks: string[]) {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });

  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(body, { status: 200 })),
  );
}

async function collect(): Promise<{ event: string; data: unknown }[]> {
  const out: { event: string; data: unknown }[] = [];
  for await (const e of streamChat({ message: "hi" })) out.push(e);
  return out;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("streamChat frame parsing", () => {
  it("parses LF-separated frames", async () => {
    mockFetchStreaming([
      'event: conversation\ndata: {"conversation_id":"conv-1"}\n\n',
      'event: message\ndata: {"text":"hello"}\n\n',
    ]);

    const events = await collect();
    expect(events.map((e) => e.event)).toEqual(["conversation", "message"]);
    expect(events[1]?.data).toEqual({ text: "hello" });
  });

  it("parses CRLF-separated frames", async () => {
    // Regression test. sse-starlette emits CRLF; a parser that only splits on
    // "\n\n" buffers the entire stream and then fails to parse the
    // concatenated result, so nothing ever renders.
    mockFetchStreaming([
      'event: intent\r\ndata: {"intent":"browse"}\r\n\r\n',
      'event: done\r\ndata: {"text":"ok","intent":"browse"}\r\n\r\n',
    ]);

    const events = await collect();
    expect(events.map((e) => e.event)).toEqual(["intent", "done"]);
    expect(events[0]?.data).toEqual({ intent: "browse" });
  });

  it("reassembles a frame split across chunk boundaries", async () => {
    mockFetchStreaming(['event: mess', 'age\r\ndata: {"te', 'xt":"split"}\r\n\r\n']);

    const events = await collect();
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ event: "message", data: { text: "split" } });
  });

  it("emits a trailing frame that has no blank line after it", async () => {
    mockFetchStreaming(['event: end\r\ndata: {"conversation_id":"conv-9"}']);

    const events = await collect();
    expect(events[0]?.event).toBe("end");
  });

  it("skips comment keep-alive lines", async () => {
    mockFetchStreaming([': ping\r\n\r\n', 'event: message\r\ndata: {"text":"hi"}\r\n\r\n']);

    const events = await collect();
    expect(events.map((e) => e.event)).toEqual(["message"]);
  });

  it("discards an unparseable frame without aborting the turn", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    mockFetchStreaming([
      "event: message\r\ndata: {not json}\r\n\r\n",
      'event: done\r\ndata: {"text":"still here","intent":null}\r\n\r\n',
    ]);

    const events = await collect();
    expect(events.map((e) => e.event)).toEqual(["done"]);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("throws when the request fails before the stream opens", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("nope", { status: 422 })),
    );

    await expect(collect()).rejects.toThrow(/422/);
  });
});
