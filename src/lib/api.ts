const API_BASE = "http://127.0.0.1:8000";

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

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(url(path, options.query), {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers
    }
  });

  if (!response.ok) {
    const body = await response.text();
    let message = body || response.statusText;
    try {
      const parsed = JSON.parse(body) as { detail?: unknown };
      const detail = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
      message = detail || response.statusText;
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
    const response = await fetch(url(path), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
  }
};
