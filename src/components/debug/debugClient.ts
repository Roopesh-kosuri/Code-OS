export type DebugState = {
  active: boolean;
  breakpoints: Record<string, number[]>;
  variables: Record<string, unknown[]>;
  stack: Array<{ id: number; name: string; line: number; source?: { path?: string } }>;
  execution?: { filePath: string; line: number };
  error?: string;
};

type Listener = (state: DebugState) => void;
const listeners = new Set<Listener>();
let socket: WebSocket | null = null;
let state: DebugState = { active: false, breakpoints: {}, variables: {}, stack: [] };

function publish(next: Partial<DebugState>) {
  state = { ...state, ...next };
  listeners.forEach((listener) => listener(state));
}

function send(command: string, extra: Record<string, unknown> = {}) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ command, ...extra }));
}

async function sessionToken(): Promise<string | null> {
  if (window.codeOS?.getSessionToken) return window.codeOS.getSessionToken();
  const response = await fetch("http://127.0.0.1:8000/api/auth/token");
  return response.ok ? ((await response.json()) as { token: string }).token : null;
}

export const debugClient = {
  subscribe(listener: Listener) { listeners.add(listener); listener(state); return () => { listeners.delete(listener); }; },
  snapshot: () => state,
  toggleBreakpoint(filePath: string, line: number) {
    const lines = new Set(state.breakpoints[filePath] ?? []);
    lines.has(line) ? lines.delete(line) : lines.add(line);
    const breakpoints = { ...state.breakpoints, [filePath]: [...lines].sort((a, b) => a - b) };
    publish({ breakpoints });
    send("set_breakpoint", { file_path: filePath, lines: breakpoints[filePath] });
  },
  async start(filePath: string) {
    const token = await sessionToken();
    const response = await fetch("http://127.0.0.1:8000/api/debug/start", {
      method: "POST", headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ file_path: filePath, args: [] }),
    });
    if (!response.ok) throw new Error(await response.text());
    const { process_id } = await response.json() as { process_id: number };
    socket = new WebSocket(`ws://127.0.0.1:8000/ws/debug/${process_id}?token=${encodeURIComponent(token ?? "")}`);
    socket.onopen = () => {
      publish({ active: true, error: undefined });
      Object.entries(state.breakpoints).forEach(([path, lines]) => send("set_breakpoint", { file_path: path, lines }));
    };
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data) as any;
      if (message.type === "event" && message.event?.event === "stopped") {
        send("get_stack"); send("get_variables");
      }
      if (message.type === "response" && message.command === "get_stack") {
        const stack = message.result?.body?.stackFrames ?? [];
        const frame = stack[0];
        publish({ stack, execution: frame?.source?.path ? { filePath: frame.source.path, line: frame.line } : undefined });
      }
      if (message.type === "response" && message.command === "get_variables") publish({ variables: message.result?.body ?? {} });
    };
    socket.onerror = () => publish({ error: "Debug connection failed" });
    socket.onclose = () => { socket = null; publish({ active: false, execution: undefined }); };
  },
  command(command: "continue" | "step_over" | "step_in" | "step_out" | "stop") { send(command); },
};
