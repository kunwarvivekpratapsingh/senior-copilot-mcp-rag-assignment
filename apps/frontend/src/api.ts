/**
 * Backend client.
 *
 * `/chat` is Server-Sent Events, but it is a POST — so `EventSource` is unusable
 * (it only issues GETs). This reads the response body as a stream and parses the
 * SSE framing directly, which is the standard workaround and keeps the request
 * shape honest rather than smuggling the question into a query string.
 */

import type { ServerStatus, ToolSpec } from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8080";

export interface StreamHandlers {
  onEvent: (event: string, payload: any) => void;
  onError: (message: string) => void;
  onDone: () => void;
}

export async function askCopilot(
  question: string,
  options: { conversationId?: string | null; confirmedActions?: string[] },
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        conversation_id: options.conversationId ?? null,
        confirmed_actions: options.confirmedActions ?? [],
      }),
      signal,
    });
  } catch (error) {
    handlers.onError(
      `Cannot reach the backend at ${BASE_URL}. Is it running? (${String(error)})`
    );
    handlers.onDone();
    return;
  }

  if (!response.ok || !response.body) {
    handlers.onError(`Backend returned ${response.status} ${response.statusText}`);
    handlers.onDone();
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      // Normalise line endings first: the SSE spec allows CRLF, LF, or a bare CR, and
      // the server emits CRLF. Splitting on "\n\n" alone would never find a boundary
      // and would merge the entire stream into a single unparseable frame.
      buffer += decoder
        .decode(value, { stream: true })
        .replace(/\r\n/g, "\n")
        .replace(/\r/g, "\n");

      // SSE frames are separated by a blank line. Keep the trailing partial frame
      // in the buffer — splitting mid-frame would drop events under load.
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        let eventName = "message";
        const dataLines: string[] = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) eventName = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (!dataLines.length) continue;
        try {
          handlers.onEvent(eventName, JSON.parse(dataLines.join("\n")));
        } catch {
          // A frame we cannot parse is skipped rather than aborting the stream:
          // losing one event is better than losing the rest of the answer.
        }
      }
    }
  } catch (error) {
    if ((error as Error).name !== "AbortError") {
      handlers.onError(`Stream interrupted: ${String(error)}`);
    }
  } finally {
    handlers.onDone();
  }
}

export async function fetchTools(): Promise<ToolSpec[]> {
  const response = await fetch(`${BASE_URL}/mcp/tools`);
  if (!response.ok) throw new Error(`tools: ${response.status}`);
  return (await response.json()).tools;
}

export async function fetchServers(): Promise<ServerStatus[]> {
  const response = await fetch(`${BASE_URL}/mcp/servers`);
  if (!response.ok) throw new Error(`servers: ${response.status}`);
  return (await response.json()).servers;
}

export { BASE_URL };
