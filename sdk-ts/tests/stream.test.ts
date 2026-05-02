import { describe, expect, it } from "vitest";

import { streamSseJson } from "../src/stream.ts";

async function collectStream<T>(body: string): Promise<T[]> {
  const encoder = new TextEncoder();
  const response = new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(body));
        controller.close();
      },
    }),
  );

  const items: T[] = [];
  for await (const item of streamSseJson<T>(response)) {
    items.push(item);
  }
  return items;
}

describe("streamSseJson", () => {
  it("parses a final SSE frame with metadata before data", async () => {
    const items = await collectStream<{ ok: boolean }>('id: 1\nevent: update\ndata: {"ok":true}');

    expect(items).toEqual([{ ok: true }]);
  });
});
