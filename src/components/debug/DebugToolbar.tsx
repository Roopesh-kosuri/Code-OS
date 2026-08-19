import { CornerDownRight, CornerUpLeft, Play, Square, StepForward } from "lucide-react";
import { debugClient } from "./debugClient";

export function DebugToolbar() {
  return <div className="flex items-center gap-1 rounded border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-amber-200">
    <button title="Continue" onClick={() => debugClient.command("continue")}><Play size={14} /></button>
    <button title="Step Over" onClick={() => debugClient.command("step_over")}><StepForward size={14} /></button>
    <button title="Step In" onClick={() => debugClient.command("step_in")}><CornerDownRight size={14} /></button>
    <button title="Step Out" onClick={() => debugClient.command("step_out")}><CornerUpLeft size={14} /></button>
    <button title="Stop Debugging" onClick={() => debugClient.command("stop")}><Square size={14} /></button>
  </div>;
}
