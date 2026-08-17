/**
 * api.ts — Typed HTTP client for the CODE-OS backend.
 *
 * Security: every request includes the session token in the Authorization
 * header so the backend middleware can reject requests from processes other
 * than this Electron renderer (e.g., JavaScript running in a browser tab that
 * tries to reach localhost:8000 via a DNS-rebinding attack).
 *
 * The token is obtained once at startup from the Electron main process via
 * the secure IPC channel (window.codeOS.getSessionToken()) and kept in module
 * memory.  It is never written to localStorage, sessionStorage, or cookies.
 *
 * In web-dev mode (no Electron, no window.codeOS) the token falls back to
 * null and Authorization headers are omitted — this is intentional because
 * the dev server is not exposed to the internet and backend auth is an
 * Electron-specific protection layer.
 */

const API_BASE = "http://127.0.0.1:8000";

// In-memory token — fetched once from Electron IPC, then reused.
let _sessionToken: string | null = null;
let _tokenFetchPromise: Promise<string | null> | null = null;

async function _ensureToken(): Promise<string | null> {
  if (_sessionToken !== null) return _sessionToken;

  if (!_tokenFetchPromise) {
    _tokenFetchPromise = (async () => {
      if (window.codeOS?.getSessionToken) {
        _sessionToken = await window.codeOS.getSessionToken();
      } else {
        try {
          const res = await fetch(`${API_BASE}/api/auth/token`);
          if (res.ok) {
            const data = (await res.json()) as { token?: string };
            _sessionToken = data.token ?? null;
          }
        } catch (e) {
          console.warn("[api] Failed to fetch session token in web mode", e);
        }
      }
      _tokenFetchPromise = null;
      return _sessionToken;
    })();
  }
  return _tokenFetchPromise;
}


type RequestOptions = RequestInit & {
  query?: Record<string, string | number | boolean | undefined | null>;
};

function url(path: string, query?: RequestOptions["query"]): string {
  const target = new URL(`${API_BASE}${path}`);
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      target.searchParams.set(key, String(value));
    }
  });
  return target.toString();
}

async function request<T>(path: string, options: RequestOptions = {}, isRetry = false): Promise<T> {
  const token = await _ensureToken();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(url(path, options.query), {
    ...options,
    headers,
  });

  if (!response.ok) {
    if (response.status === 401 && !isRetry) {
      _sessionToken = null;
      _tokenFetchPromise = null;
      await _ensureToken();
      return request<T>(path, options, true);
    }

    const body = await response.text();
    let message = body || response.statusText;
    try {
      const parsed = JSON.parse(body) as { detail?: unknown; error?: unknown };
      const rawDetail = parsed.detail ?? parsed.error;
      const detail = typeof rawDetail === "string" ? rawDetail : (rawDetail ? JSON.stringify(rawDetail) : "");
      message = detail || body || response.statusText;
    } catch {
      message = body || response.statusText;
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"]) => request<T>(path, { query }),
  post: <T>(path: string, body?: unknown, query?: RequestOptions["query"]) =>
    request<T>(path, {
      method: "POST",
      query,
      body: body === undefined ? undefined : JSON.stringify(body)
    }),
  put: <T>(path: string, body?: unknown, query?: RequestOptions["query"]) =>
    request<T>(path, {
      method: "PUT",
      query,
      body: body === undefined ? undefined : JSON.stringify(body)
    }),
  delete: <T>(path: string, query?: RequestOptions["query"]) =>
    request<T>(path, {
      method: "DELETE",
      query
    }),
  stream: async (path: string, body: unknown, onToken: (token: string) => void, signal?: AbortSignal) => {
    const sessionToken = await _ensureToken();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (sessionToken) {
      headers["Authorization"] = `Bearer ${sessionToken}`;
    }
    const response = await fetch(url(path), {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal
    });
    if (!response.ok || !response.body) {
      throw new Error(await response.text());
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    for (;;) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      onToken(decoder.decode(value, { stream: true }));
    }
  },
  /**
   * Stream Server-Sent Events (SSE) from the backend.
   * Unlike `stream()` which passes raw bytes, this parses SSE `event:` and `data:` lines
   * and calls the typed callback with parsed event objects.
   */
  streamSSE: async (
    path: string,
    body: unknown,
    onEvent: (eventType: string, data: unknown) => void,
    signal?: AbortSignal
  ) => {
    const sessionToken = await _ensureToken();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (sessionToken) {
      headers["Authorization"] = `Bearer ${sessionToken}`;
    }
    const response = await fetch(url(path), {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal,
    });
    if (!response.ok || !response.body) {
      throw new Error(await response.text());
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Parse SSE: split on double-newline (event boundary)
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? ""; // Keep incomplete last chunk

      for (const part of parts) {
        if (!part.trim()) continue;
        let eventType = "message";
        let dataStr = "";
        for (const rawLine of part.split("\n")) {
          const line = rawLine.replace(/\r$/, "");
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            dataStr += line.slice(6);
          }
        }
        if (dataStr) {
          try {
            onEvent(eventType, JSON.parse(dataStr));
          } catch {
            onEvent(eventType, dataStr);
          }
        }
      }
    }

    // Process any remaining buffer
    if (buffer.trim()) {
      let eventType = "message";
      let dataStr = "";
      for (const rawLine of buffer.split("\n")) {
        const line = rawLine.replace(/\r$/, "");
        if (line.startsWith("event: ")) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          dataStr += line.slice(6);
        }
      }
      if (dataStr) {
        try {
          onEvent(eventType, JSON.parse(dataStr));
        } catch {
          onEvent(eventType, dataStr);
        }
      }
    }
  },
};
