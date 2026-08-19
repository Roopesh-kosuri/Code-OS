import { useEffect, useState } from "react";
import { Bug } from "lucide-react";
import { DebugState, debugClient } from "./debugClient";

const initial: DebugState = debugClient.snapshot();
export function DebugPanel() {
  const [debug, setDebug] = useState(initial);
  useEffect(() => debugClient.subscribe(setDebug), []);
  return <aside className="border-t border-amber-400/20 bg-surface-container-low p-3 text-xs">
    <div className="mb-2 flex items-center gap-2 font-semibold"><Bug size={14} />Debug</div>
    <div className="mb-3"><div className="mb-1 uppercase text-on-surface-variant">Variables</div><pre className="max-h-36 overflow-auto rounded bg-black/20 p-2">{JSON.stringify(debug.variables, null, 2)}</pre></div>
    <div><div className="mb-1 uppercase text-on-surface-variant">Call Stack</div>{debug.stack.map((frame) => <div key={frame.id} className="truncate">{frame.name} — {frame.source?.path}:{frame.line}</div>)}</div>
    {debug.error && <p className="mt-2 text-error">{debug.error}</p>}
  </aside>;
}
