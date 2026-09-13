/**
 * sse.ts — Authenticated SSE Transport Helper (AUD-010).
 *
 * Provides a unified, authenticated EventSource connection wrapper for:
 * - teamStore (/api/team/jobs/:id/events)
 * - marathonStore (/api/marathon/:id/stream)
 * - agenticTerminalStore (/api/terminal/stream/:id)
 *
 * Security:
 * Mints short-lived (TTL <= 60s), single-purpose stream tokens scoped to the requested
 * route via POST /api/auth/stream-token before establishing the EventSource stream.
 * On connection drops or reconnects, a fresh scoped token is minted automatically.
 *
 * Resilience:
 * Implements exponential backoff reconnects on drop and ensures complete listener
 * and timer cleanup on unmount/close to prevent duplicate listeners or connection leaks.
 */

import { api, API_BASE } from "./api";

export interface AuthenticatedSSEOptions {
  route: string; // The backend route, e.g. `/api/team/jobs/${id}/events`
  query?: Record<string, string | number | boolean | undefined | null>;
  events?: Record<string, (event: MessageEvent) => void>;
  onMessage?: (event: MessageEvent) => void;
  onOpen?: (event: Event) => void;
  onError?: (event: Event | Error) => void;
  maxReconnectAttempts?: number; // default: 10
  baseDelayMs?: number; // default: 1000
  maxDelayMs?: number; // default: 8000
  shouldReconnect?: () => boolean; // optional check whether reconnection should proceed
}

export interface AuthenticatedSSEStream {
  close: () => void;
  getState: () => "connecting" | "connected" | "error" | "closed";
}

export function createAuthenticatedSSEStream(options: AuthenticatedSSEOptions): AuthenticatedSSEStream {
  const {
    route,
    query,
    events,
    onMessage,
    onOpen,
    onError,
    maxReconnectAttempts = 10,
    baseDelayMs = 1000,
    maxDelayMs = 8000,
    shouldReconnect,
  } = options;

  let currentSource: EventSource | null = null;
  let reconnectTimer: any = null;
  let attempts = 0;
  let isClosed = false;
  let state: "connecting" | "connected" | "error" | "closed" = "connecting";

  // Parse path and query parts from route string
  const [pathPart, routeQueryStr] = route.split("?");
  const cleanRoute = pathPart.replace(/\/+$/, "");

  async function connect() {
    if (isClosed) return;

    state = "connecting";

    let token = "";
    try {
      const resp = await api.post<{ token: string }>("/api/auth/stream-token", { route: cleanRoute });
      token = resp?.token ?? "";
    } catch (err: any) {
      if (isClosed) return;
      state = "error";
      onError?.(err instanceof Error ? err : new Error(String(err)));
      scheduleReconnect();
      return;
    }

    if (isClosed) return;

    try {
      const base = cleanRoute.startsWith("http://") || cleanRoute.startsWith("https://") ? "" : API_BASE;
      const targetUrl = new URL(`${base}${cleanRoute}`);

      // Apply query params from route string
      if (routeQueryStr) {
        const params = new URLSearchParams(routeQueryStr);
        params.forEach((val, key) => {
          targetUrl.searchParams.set(key, val);
        });
      }

      // Apply query params from options.query
      if (query) {
        for (const [key, value] of Object.entries(query)) {
          if (value !== undefined && value !== null) {
            targetUrl.searchParams.set(key, String(value));
          }
        }
      }

      // Attach scoped stream token if present
      if (token) {
        targetUrl.searchParams.set("token", token);
      }

      const es = new EventSource(targetUrl.toString());
      currentSource = es;

      es.onopen = (evt) => {
        if (isClosed) {
          es.close();
          return;
        }
        state = "connected";
        attempts = 0;
        onOpen?.(evt);
      };

      if (onMessage) {
        es.onmessage = (evt) => {
          if (!isClosed) {
            onMessage(evt);
          }
        };
      }

      if (events) {
        for (const [eventName, handler] of Object.entries(events)) {
          es.addEventListener(eventName, (evt: MessageEvent) => {
            if (!isClosed) {
              handler(evt);
            }
          });
        }
      }

      es.onerror = (evt) => {
        if (isClosed) return;
        state = "error";
        es.close();
        if (currentSource === es) {
          currentSource = null;
        }
        onError?.(evt);
        scheduleReconnect();
      };
    } catch (err: any) {
      if (isClosed) return;
      state = "error";
      onError?.(err instanceof Error ? err : new Error(String(err)));
      scheduleReconnect();
    }
  }

  function scheduleReconnect() {
    if (isClosed) return;
    if (shouldReconnect && !shouldReconnect()) {
      return;
    }
    if (attempts >= maxReconnectAttempts) {
      return;
    }

    attempts++;
    const delay = Math.min(baseDelayMs * Math.pow(2, attempts - 1), maxDelayMs);

    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
    }
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  }

  function close() {
    isClosed = true;
    state = "closed";
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (currentSource) {
      currentSource.close();
      currentSource = null;
    }
  }

  // Initial connection
  connect();

  return {
    close,
    getState: () => state,
  };
}
