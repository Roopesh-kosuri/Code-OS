import React, { useState, useMemo, useRef } from "react";
import {
  Layers,
  Terminal,
  ShieldCheck,
  FlaskConical,
  Server,
  CheckCircle2,
  AlertCircle,
  Clock,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  Maximize2,
  X,
  FileCode,
  ArrowRight,
  Info,
  type LucideIcon,
} from "lucide-react";
import { useTeamStore, TeamTask, TeamRole } from "./teamStore";

const ROLE_ICONS: Record<string, LucideIcon> = {
  architect: Layers,
  coder: Terminal,
  reviewer: ShieldCheck,
  tester: FlaskConical,
  devops: Server,
};

const ROLE_COLORS: Record<string, { text: string; bg: string; border: string }> = {
  architect: { text: "text-purple-400", bg: "bg-purple-500/10", border: "border-purple-500/30" },
  coder: { text: "text-emerald-400", bg: "bg-emerald-500/10", border: "border-emerald-500/30" },
  reviewer: { text: "text-amber-400", bg: "bg-amber-500/10", border: "border-amber-500/30" },
  tester: { text: "text-cyan-400", bg: "bg-cyan-500/10", border: "border-cyan-500/30" },
  devops: { text: "text-rose-400", bg: "bg-rose-500/10", border: "border-rose-500/30" },
};

interface NodePosition {
  task: TeamTask;
  x: number;
  y: number;
  layer: number;
}

export const DAGBoard: React.FC = () => {
  const { tasks, selectedTaskId, selectTask, teamMessages, handoffs } = useTeamStore();

  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 40, y: 40 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0 });

  const NODE_WIDTH = 220;
  const NODE_HEIGHT = 80;
  const LAYER_GAP_X = 140;
  const NODE_GAP_Y = 30;

  // Compute 2D topological positions for tasks
  const layoutNodes = useMemo(() => {
    if (!tasks || tasks.length === 0) return [];

    const taskMap = new Map<string, TeamTask>();
    tasks.forEach((t) => taskMap.set(t.id, t));

    // Calculate topological depth of each task
    const depths = new Map<string, number>();

    const getDepth = (id: string, visited = new Set<string>()): number => {
      if (depths.has(id)) return depths.get(id)!;
      if (visited.has(id)) return 0; // Break cycle
      visited.add(id);

      const task = taskMap.get(id);
      if (!task || !task.dependencies || task.dependencies.length === 0) {
        depths.set(id, 0);
        return 0;
      }

      let maxD = 0;
      for (const depId of task.dependencies) {
        if (taskMap.has(depId)) {
          maxD = Math.max(maxD, getDepth(depId, new Set(visited)) + 1);
        }
      }
      depths.set(id, maxD);
      return maxD;
    };

    tasks.forEach((t) => getDepth(t.id));

    // Group tasks into layers
    const layers: Record<number, TeamTask[]> = {};
    tasks.forEach((t) => {
      const d = depths.get(t.id) || 0;
      if (!layers[d]) layers[d] = [];
      layers[d].push(t);
    });

    // Compute coordinates
    const positions: NodePosition[] = [];
    Object.entries(layers).forEach(([layerStr, layerTasks]) => {
      const layerIdx = parseInt(layerStr, 10);
      layerTasks.forEach((task, idxInLayer) => {
        positions.push({
          task,
          layer: layerIdx,
          x: layerIdx * (NODE_WIDTH + LAYER_GAP_X),
          y: idxInLayer * (NODE_HEIGHT + NODE_GAP_Y),
        });
      });
    });

    return positions;
  }, [tasks]);

  // Compute dependency edges (Bezier curves)
  const edges = useMemo(() => {
    const nodeMap = new Map<string, NodePosition>();
    layoutNodes.forEach((n) => nodeMap.set(n.task.id, n));

    const result: { from: NodePosition; to: NodePosition; path: string }[] = [];

    layoutNodes.forEach((toNode) => {
      toNode.task.dependencies.forEach((depId) => {
        const fromNode = nodeMap.get(depId);
        if (fromNode) {
          const startX = fromNode.x + NODE_WIDTH;
          const startY = fromNode.y + NODE_HEIGHT / 2;
          const endX = toNode.x;
          const endY = toNode.y + NODE_HEIGHT / 2;
          const cX = (startX + endX) / 2;

          const path = `M ${startX} ${startY} C ${cX} ${startY}, ${cX} ${endY}, ${endX} ${endY}`;
          result.push({ from: fromNode, to: toNode, path });
        }
      });
    });

    return result;
  }, [layoutNodes]);

  // Pan interaction handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest("[data-task-node]")) return;
    setIsDragging(true);
    dragStartRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return;
    setPan({
      x: e.clientX - dragStartRef.current.x,
      y: e.clientY - dragStartRef.current.y,
    });
  };

  const handleMouseUp = () => setIsDragging(false);

  const handleZoom = (delta: number) => {
    setZoom((z) => Math.min(Math.max(0.4, z + delta), 2));
  };

  const resetView = () => {
    setZoom(1);
    setPan({ x: 40, y: 40 });
  };

  const selectedTask = useMemo(
    () => tasks.find((t) => t.id === selectedTaskId),
    [tasks, selectedTaskId]
  );

  const selectedTaskMessages = useMemo(
    () => (selectedTaskId ? teamMessages.filter((m) => m.task_id === selectedTaskId) : []),
    [teamMessages, selectedTaskId]
  );

  const selectedTaskHandoffs = useMemo(
    () => (selectedTaskId ? handoffs.filter((h) => h.task_id === selectedTaskId) : []),
    [handoffs, selectedTaskId]
  );

  return (
    <div className="relative w-full h-full flex overflow-hidden bg-[#0c0c0e] rounded-xl border border-white/5 select-none">
      {/* Canvas Controls Toolbar */}
      <div className="absolute top-3 left-3 z-20 flex items-center gap-1.5 bg-surface-container/90 backdrop-blur-md border border-white/10 rounded-lg p-1.5 shadow-lg">
        <button
          onClick={() => handleZoom(0.15)}
          className="p-1.5 rounded hover:bg-surface-variant text-on-surface-variant hover:text-on-surface cursor-pointer"
          title="Zoom In"
        >
          <ZoomIn size={14} />
        </button>
        <button
          onClick={() => handleZoom(-0.15)}
          className="p-1.5 rounded hover:bg-surface-variant text-on-surface-variant hover:text-on-surface cursor-pointer"
          title="Zoom Out"
        >
          <ZoomOut size={14} />
        </button>
        <div className="w-[1px] h-4 bg-white/10 mx-0.5" />
        <button
          onClick={resetView}
          className="p-1.5 rounded hover:bg-surface-variant text-on-surface-variant hover:text-on-surface cursor-pointer"
          title="Fit / Reset View"
        >
          <Maximize2 size={14} />
        </button>
        <span className="text-[10px] font-mono text-on-surface-variant px-1">
          {Math.round(zoom * 100)}%
        </span>
      </div>

      {/* Main 2D DAG Graph Viewport */}
      <div
        className={`flex-1 h-full cursor-grab ${isDragging ? "cursor-grabbing" : ""}`}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {tasks.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-on-surface-variant/60 gap-3">
            <Layers size={32} className="opacity-40 animate-pulse" />
            <p className="text-xs">No active DAG workflow. Submit a task to launch the team.</p>
          </div>
        ) : (
          <div
            style={{
              transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
              transformOrigin: "0 0",
              transition: isDragging ? "none" : "transform 0.1s ease-out",
            }}
            className="relative"
          >
            {/* SVG Connecting Edges */}
            <svg
              className="absolute top-0 left-0 pointer-events-none overflow-visible"
              style={{ width: 1, height: 1 }}
            >
              <defs>
                <marker
                  id="arrow-default"
                  viewBox="0 0 10 10"
                  refX="8"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 1 L 9 5 L 0 9 z" fill="#4B5563" />
                </marker>
                <marker
                  id="arrow-active"
                  viewBox="0 0 10 10"
                  refX="8"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 1 L 9 5 L 0 9 z" fill="#3B82F6" />
                </marker>
              </defs>

              {edges.map((edge, idx) => {
                const isFromDone = edge.from.task.status === "completed";
                const isToRunning = edge.to.task.status === "running";
                const strokeColor = isToRunning
                  ? "#3B82F6"
                  : isFromDone
                  ? "#10B981"
                  : "#374151";

                return (
                  <path
                    key={`edge-${idx}`}
                    d={edge.path}
                    fill="none"
                    stroke={strokeColor}
                    strokeWidth={isToRunning ? "2.5" : "1.8"}
                    strokeDasharray={isToRunning ? "4 2" : "none"}
                    className={isToRunning ? "animate-pulse" : ""}
                    markerEnd={isToRunning ? "url(#arrow-active)" : "url(#arrow-default)"}
                  />
                );
              })}
            </svg>

            {/* Task Nodes */}
            {layoutNodes.map(({ task, x, y }) => {
              const isVerification =
                task.title?.toLowerCase().includes("verif") ||
                task.id?.toLowerCase().includes("verif") ||
                task.assigned_agent === "verifier";

              const RoleIcon = isVerification ? ShieldCheck : (ROLE_ICONS[task.assigned_agent] || Terminal);
              const roleTheme = isVerification
                ? { text: "text-purple-300", bg: "bg-purple-500/20", border: "border-purple-500/50" }
                : (ROLE_COLORS[task.assigned_agent] || ROLE_COLORS.coder);
              const isSelected = selectedTaskId === task.id;

              // Node status appearance
              let statusBorder = isVerification ? "border-purple-500/40" : "border-white/10";
              let statusGlow = isVerification ? "shadow-purple-500/10" : "";
              if (task.status === "running") {
                statusBorder = isVerification
                  ? "border-purple-400 ring-2 ring-purple-500/40"
                  : "border-primary-container ring-2 ring-primary-container/20";
                statusGlow = isVerification
                  ? "shadow-lg shadow-purple-500/20"
                  : "shadow-lg shadow-primary-container/10";
              } else if (task.status === "completed") {
                statusBorder = isVerification ? "border-purple-400/60" : "border-emerald-500/40";
              } else if (task.status === "failed") {
                statusBorder = "border-error ring-1 ring-error/30";
              }

              return (
                <div
                  key={task.id}
                  data-task-node
                  data-testid={`dag-node-${task.id}`}
                  onClick={() => selectTask(task.id)}
                  style={{
                    position: "absolute",
                    left: `${x}px`,
                    top: `${y}px`,
                    width: `${NODE_WIDTH}px`,
                    height: `${NODE_HEIGHT}px`,
                  }}
                  className={`rounded-xl p-3 ${
                    isVerification ? "bg-purple-950/30 border-purple-500/40" : "bg-surface-container-low/95"
                  } backdrop-blur-sm border ${statusBorder} ${statusGlow} ${
                    isSelected ? "ring-2 ring-white/60" : ""
                  } hover:bg-surface-container cursor-pointer transition-all flex flex-col justify-between shadow-md group`}
                >
                  {/* Node Header: Role + Status */}
                  <div className="flex justify-between items-center">
                    <div className="flex items-center gap-1.5">
                      <div className={`p-1 rounded ${roleTheme.bg} ${roleTheme.text}`}>
                        <RoleIcon size={12} />
                      </div>
                      <span className="text-[10px] font-mono text-on-surface-variant lowercase">
                        @{task.assigned_agent}
                      </span>
                    </div>

                    {/* Status Indicator */}
                    {task.status === "running" && (
                      <span className="flex items-center gap-1 text-[10px] text-primary-container font-bold">
                        <span className="w-1.5 h-1.5 rounded-full bg-primary-container animate-ping" />
                        RUNNING
                      </span>
                    )}
                    {task.status === "completed" && (
                      <span className="flex items-center gap-1 text-[10px] text-emerald-400">
                        <CheckCircle2 size={12} />
                        DONE
                      </span>
                    )}
                    {task.status === "failed" && (
                      <span className="flex items-center gap-1 text-[10px] text-error">
                        <AlertCircle size={12} />
                        FAIL
                      </span>
                    )}
                    {task.status === "queued" && (
                      <span className="text-[10px] text-on-surface-variant/60 font-mono">
                        QUEUED
                      </span>
                    )}
                    {task.status === "pending" && (
                      <span className="text-[10px] text-on-surface-variant/40 font-mono">
                        WAITING
                      </span>
                    )}
                  </div>

                  {/* Task Title */}
                  <div className="text-xs font-semibold text-on-surface truncate group-hover:text-primary-container transition-colors">
                    {task.title}
                  </div>

                  {/* Footer: Duration / Dependencies */}
                  <div className="flex items-center justify-between text-[10px] font-mono text-on-surface-variant/80 border-t border-white/5 pt-1">
                    <div className="flex items-center gap-1">
                      {task.duration_seconds !== undefined && task.duration_seconds !== null ? (
                        <>
                          <Clock size={10} />
                          <span>{task.duration_seconds.toFixed(1)}s</span>
                        </>
                      ) : (
                        <span>id: {task.id.slice(0, 6)}</span>
                      )}
                    </div>
                    {task.dependencies.length > 0 && (
                      <span className="text-[9px] text-on-surface-variant/60">
                        deps: {task.dependencies.length}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Task Details Side Panel */}
      {selectedTask && (
        <div
          data-testid="dag-task-details"
          className="w-80 h-full border-l border-white/10 bg-surface-container-low flex flex-col z-30 shadow-2xl overflow-y-auto"
        >
          {/* Panel Header */}
          <div className="p-4 border-b border-white/10 flex justify-between items-start">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-on-surface-variant">
                  {selectedTask.id}
                </span>
                <span
                  className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${
                    selectedTask.status === "running"
                      ? "bg-primary-container/20 text-primary-container"
                      : selectedTask.status === "completed"
                      ? "bg-emerald-500/20 text-emerald-300"
                      : selectedTask.status === "failed"
                      ? "bg-error/20 text-error"
                      : "bg-white/5 text-on-surface-variant"
                  }`}
                >
                  {selectedTask.status}
                </span>
              </div>
              <h3 className="text-sm font-bold text-on-surface leading-snug">
                {selectedTask.title}
              </h3>
            </div>
            <button
              onClick={() => selectTask(null)}
              className="p-1 rounded hover:bg-surface-variant text-on-surface-variant hover:text-on-surface cursor-pointer"
            >
              <X size={14} />
            </button>
          </div>

          {/* Details Content */}
          <div className="p-4 flex flex-col gap-4 text-xs">
            {/* Agent Role */}
            <div className="bg-surface-container rounded-lg p-3 flex justify-between items-center">
              <span className="text-on-surface-variant">Assigned Role:</span>
              <span className="font-bold text-on-surface uppercase font-mono">
                @{selectedTask.assigned_agent}
              </span>
            </div>

            {/* Timings */}
            {selectedTask.duration_seconds !== undefined && selectedTask.duration_seconds !== null && (
              <div className="bg-surface-container rounded-lg p-3 flex justify-between items-center font-mono">
                <span className="text-on-surface-variant">Execution Time:</span>
                <span className="text-emerald-400 font-bold">
                  {selectedTask.duration_seconds.toFixed(2)}s
                </span>
              </div>
            )}

            {/* Dependencies */}
            <div>
              <h4 className="text-[11px] font-bold text-on-surface uppercase tracking-wider mb-2">
                Dependencies ({selectedTask.dependencies.length})
              </h4>
              {selectedTask.dependencies.length === 0 ? (
                <span className="text-[11px] text-on-surface-variant/60 italic">None (Root Step)</span>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {selectedTask.dependencies.map((dep) => (
                    <div
                      key={dep}
                      className="p-2 rounded bg-surface-container text-on-surface font-mono text-[11px] flex items-center gap-1.5"
                    >
                      <ArrowRight size={12} className="text-primary-container" />
                      <span>{dep}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Error Message (if failed) */}
            {selectedTask.errors && (
              <div className="rounded-lg p-3 bg-error/10 border border-error/30 text-error">
                <div className="font-bold mb-1 flex items-center gap-1">
                  <AlertCircle size={14} />
                  Error Details:
                </div>
                <div className="font-mono text-[11px] break-all">{selectedTask.errors}</div>
              </div>
            )}

            {/* Associated Handoffs */}
            {selectedTaskHandoffs.length > 0 && (
              <div>
                <h4 className="text-[11px] font-bold text-on-surface uppercase tracking-wider mb-2">
                  Handoff Artifacts ({selectedTaskHandoffs.length})
                </h4>
                <div className="flex flex-col gap-2">
                  {selectedTaskHandoffs.map((h, i) => (
                    <div
                      key={i}
                      className="rounded-lg p-2.5 bg-surface-container border border-white/5 flex flex-col gap-1"
                    >
                      <div className="flex justify-between text-[10px] text-on-surface-variant font-mono">
                        <span>@{h.from_role} → @{h.to_role}</span>
                        <span className="uppercase text-primary-container">{h.type}</span>
                      </div>
                      <p className="text-[11px] text-on-surface">{h.summary}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Associated Messages */}
            {selectedTaskMessages.length > 0 && (
              <div>
                <h4 className="text-[11px] font-bold text-on-surface uppercase tracking-wider mb-2">
                  Task Chatter ({selectedTaskMessages.length})
                </h4>
                <div className="flex flex-col gap-2">
                  {selectedTaskMessages.map((m, i) => (
                    <div key={i} className="p-2 rounded bg-surface-container text-[11px]">
                      <div className="font-bold text-primary-container mb-0.5">
                        @{m.sender_role}
                      </div>
                      <p className="text-on-surface-variant">{m.content}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
