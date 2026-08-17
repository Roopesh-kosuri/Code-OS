import { useWorkspaceStore } from "../../stores/workspaceStore";

interface WelcomeScreenProps {
  backendDown?: boolean;
}

export function WelcomeScreen({ backendDown = false }: WelcomeScreenProps) {
  const openWorkspace = useWorkspaceStore((state) => state.openWorkspace);
  const activeWorkspaces = useWorkspaceStore((state) => state.activeWorkspaces);
  const selectWorkspaceForPath = useWorkspaceStore((state) => state.selectWorkspaceForPath);

  // Shared classes for action buttons based on backend state
  const actionBtnBase =
    "flex items-center gap-3 p-4 rounded-lg border transition-all w-full text-left group";
  const actionBtnEnabled =
    `${actionBtnBase} border-white/5 hover:border-primary/30 hover:bg-white/5 cursor-pointer`;
  const actionBtnDisabled =
    `${actionBtnBase} border-white/5 opacity-40 cursor-not-allowed pointer-events-none`;

  const handleAction = (e: React.MouseEvent) => {
    if (backendDown) {
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    void openWorkspace();
  };

  return (
    <div className="bg-[#131314] text-on-surface h-full w-full overflow-hidden relative flex items-center justify-center font-body-sm text-body-sm select-none">
      {/* Ambient Background Glows */}
      <div className="absolute top-[-10vw] left-[-10vw] w-[40vw] h-[40vw] bg-[#00e5ff] rounded-full blur-[120px] opacity-10 pointer-events-none" />
      <div className="absolute bottom-[-5vw] right-[-5vw] w-[30vw] h-[30vw] bg-[#c2aef0] rounded-full blur-[120px] opacity-10 pointer-events-none" />

      {/* Main Launcher Container */}
      <main className="glass-panel w-full max-w-[850px] rounded-xl flex flex-col relative z-10 overflow-hidden shadow-2xl">
        {/* Header */}
        <header className="flex items-center gap-4 p-6 border-b border-white/5">
          <div className="w-12 h-12 rounded-lg bg-surface-container flex items-center justify-center border border-white/5">
            <span className="material-symbols-outlined text-primary text-[28px]">terminal</span>
          </div>
          <div>
            <h1 className="font-headline-lg text-headline-lg text-on-surface font-bold tracking-tighter">CODE OS</h1>
            <p className="font-micro-label text-micro-label text-on-surface-variant uppercase mt-1">High-Performance Environment</p>
          </div>
        </header>

        {/* Backend-down warning panel */}
        {backendDown && (
          <div className="mx-6 mt-4 p-4 rounded-lg bg-red-950/60 border border-red-500/40 flex items-start gap-3">
            <span className="material-symbols-outlined text-red-400 text-[22px] shrink-0 mt-0.5">error</span>
            <div>
              <p className="font-semibold text-red-300 text-sm mb-1">Backend Offline — Actions Unavailable</p>
              <p className="text-red-200/80 text-xs leading-relaxed">
                The CODE OS Python backend failed to start. This usually means Python 3.11+
                is not installed on this system.
              </p>
              <p className="text-red-200/80 text-xs leading-relaxed mt-1">
                <strong className="text-red-300">Fix:</strong> Install Python 3.11 or newer from{" "}
                <button
                  className="text-cyan-400 hover:text-cyan-300 underline bg-transparent border-none cursor-pointer p-0 font-semibold"
                  onClick={() => {
                    if (window.codeOS?.openExternal) {
                      void window.codeOS.openExternal("https://python.org/downloads");
                    }
                  }}
                >
                  python.org/downloads
                </button>
                {" "}(on Windows, tick <em>"Add Python to PATH"</em>), then{" "}
                <strong className="text-red-300">relaunch CODE OS</strong>.
              </p>
            </div>
          </div>
        )}

        {/* Content Grid */}
        <div className="grid grid-cols-1 md:grid-cols-5 bg-white/5 flex-grow min-h-[380px] mt-4">
          {/* Left: Recent Projects */}
          <section className="md:col-span-3 glass-panel h-full border-none rounded-none p-6 flex flex-col">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-micro-label text-micro-label text-on-surface-variant">RECENT PROJECTS</h2>
              <span className="material-symbols-outlined text-outline-variant cursor-pointer hover:text-primary transition-colors text-[18px]">search</span>
            </div>
            <ul className="flex flex-col gap-1 overflow-y-auto pr-2 flex-1 max-h-[280px]">
              {activeWorkspaces.length > 0 ? (
                activeWorkspaces.map((ws) => (
                  <li key={ws.path}>
                    <button
                      onClick={() => !backendDown && selectWorkspaceForPath(ws.path)}
                      disabled={backendDown}
                      className={`w-full flex items-center gap-3 p-3 rounded-lg transition-colors text-left group ${
                        backendDown
                          ? "opacity-40 cursor-not-allowed"
                          : "hover:bg-white/5 cursor-pointer"
                      }`}
                    >
                      <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary transition-colors text-[20px]">folder_open</span>
                      <div className="flex flex-col min-w-0 flex-1">
                        <span className="font-code-block text-code-block text-on-surface group-hover:text-primary transition-colors truncate">
                          {ws.name}
                        </span>
                        <span className="font-micro-label text-micro-label text-on-surface-variant mt-0.5 truncate">
                          {ws.path}
                        </span>
                      </div>
                      <span className="material-symbols-outlined text-outline-variant opacity-0 group-hover:opacity-100 transition-opacity text-[18px]">chevron_right</span>
                    </button>
                  </li>
                ))
              ) : (
                <div className="p-4 text-xs text-on-surface-variant/50 italic border border-dashed border-white/10 rounded-lg text-center my-auto">
                  {backendDown
                    ? "Start the backend to load recent workspaces."
                    : "No recent workspaces. Click Open Folder to start."}
                </div>
              )}
            </ul>
          </section>

          {/* Right: Actions */}
          <section className="md:col-span-2 glass-panel h-full border-none rounded-none p-6 flex flex-col gap-4 bg-surface-container-low/50">
            <h2 className="font-micro-label text-micro-label text-on-surface-variant mb-1">QUICK ACTIONS</h2>

            {/* New Project */}
            <div className="relative group/tip">
              <button
                onClick={handleAction}
                disabled={backendDown}
                className={backendDown ? actionBtnDisabled : actionBtnEnabled}
              >
                <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary transition-colors text-[24px]">add_box</span>
                <div>
                  <span className="block font-body-sm text-body-sm text-on-surface font-semibold">New Project</span>
                  <span className="block font-micro-label text-micro-label text-on-surface-variant mt-0.5">Initialize empty environment</span>
                </div>
              </button>
              {backendDown && (
                <div className="absolute left-1/2 -translate-x-1/2 -top-8 bg-surface-container-highest border border-red-500/30 text-red-300 text-[10px] px-2 py-1 rounded whitespace-nowrap opacity-0 group-hover/tip:opacity-100 pointer-events-none transition-opacity z-50">
                  Backend offline — install Python 3.11+ first
                </div>
              )}
            </div>

            {/* Open Folder */}
            <div className="relative group/tip">
              <button
                onClick={handleAction}
                disabled={backendDown}
                className={backendDown ? actionBtnDisabled : actionBtnEnabled}
              >
                <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary transition-colors text-[24px]">file_open</span>
                <div>
                  <span className="block font-body-sm text-body-sm text-on-surface font-semibold">Open Folder</span>
                  <span className="block font-micro-label text-micro-label text-on-surface-variant mt-0.5">Browse local directories</span>
                </div>
              </button>
              {backendDown && (
                <div className="absolute left-1/2 -translate-x-1/2 -top-8 bg-surface-container-highest border border-red-500/30 text-red-300 text-[10px] px-2 py-1 rounded whitespace-nowrap opacity-0 group-hover/tip:opacity-100 pointer-events-none transition-opacity z-50">
                  Backend offline — install Python 3.11+ first
                </div>
              )}
            </div>

            {/* Clone Repo */}
            <div className="relative group/tip">
              <button
                onClick={handleAction}
                disabled={backendDown}
                className={backendDown ? actionBtnDisabled : actionBtnEnabled}
              >
                <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary transition-colors text-[24px]">cloud_download</span>
                <div>
                  <span className="block font-body-sm text-body-sm text-on-surface font-semibold">Clone Repo</span>
                  <span className="block font-micro-label text-micro-label text-on-surface-variant mt-0.5">Import from remote source</span>
                </div>
              </button>
              {backendDown && (
                <div className="absolute left-1/2 -translate-x-1/2 -top-8 bg-surface-container-highest border border-red-500/30 text-red-300 text-[10px] px-2 py-1 rounded whitespace-nowrap opacity-0 group-hover/tip:opacity-100 pointer-events-none transition-opacity z-50">
                  Backend offline — install Python 3.11+ first
                </div>
              )}
            </div>
          </section>
        </div>

        {/* Footer */}
        <footer className="p-6 border-t border-white/5 flex justify-end items-center bg-surface-container/30">
          <button
            onClick={handleAction}
            disabled={backendDown}
            title={backendDown ? "Backend offline — install Python 3.11+ and relaunch" : undefined}
            className={`font-micro-label text-micro-label px-6 py-3 rounded-full flex items-center gap-2 uppercase tracking-wider font-bold transition-all transform ${
              backendDown
                ? "bg-surface-container text-on-surface-variant/40 opacity-50 cursor-not-allowed"
                : "bg-primary-container text-on-primary-container shadow-[0_0_15px_rgba(0,229,255,0.3)] hover:shadow-[0_0_25px_rgba(0,229,255,0.5)] hover:-translate-y-0.5"
            }`}
          >
            {backendDown ? "Backend Offline" : "Get Started"}
            <span className="material-symbols-outlined text-[16px]">
              {backendDown ? "block" : "arrow_forward"}
            </span>
          </button>
        </footer>
      </main>
    </div>
  );
}
