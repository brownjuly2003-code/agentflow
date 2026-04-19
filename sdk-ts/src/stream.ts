import { AgentFlowError } from "./exceptions.js";

export async function* streamSseJson<T>(
  response: Response,
  signal?: AbortSignal,
): AsyncGenerator<T> {
  if (!response.body) {
    throw new AgentFlowError("SSE response body is empty");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) {
        await reader.cancel();
        return;
      }

      const chunk = await reader.read();
      if (chunk.done) {
        break;
      }

      buffer += decoder.decode(chunk.value, { stream: true }).replace(/\r\n/g, "\n");

      for (;;) {
        const boundaryIndex = buffer.indexOf("\n\n");
        if (boundaryIndex === -1) {
          break;
        }

        const frame = buffer.slice(0, boundaryIndex);
        buffer = buffer.slice(boundaryIndex + 2);

        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");

        if (data) {
          yield JSON.parse(data) as T;
        }
      }
    }

    buffer += decoder.decode().replace(/\r\n/g, "\n");
    if (buffer.trim().startsWith("data:")) {
      const data = buffer
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (data) {
        yield JSON.parse(data) as T;
      }
    }
  } catch (error) {
    if (error instanceof AgentFlowError) {
      throw error;
    }
    if (error instanceof Error) {
      throw new AgentFlowError(`Failed to read SSE stream: ${error.message}`);
    }
    throw new AgentFlowError("Failed to read SSE stream");
  } finally {
    reader.releaseLock();
  }
}
