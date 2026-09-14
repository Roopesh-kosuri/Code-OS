# CODE OS v5.0.0 Release Notes

**Release Date:** September 14, 2026

## What's New

### 🚀 Marathon Autopilot
Execute massive, multi-day projects autonomously. Define a goal (e.g.,
"Rewrite the backend from Express to FastAPI"), and CODE OS decomposes it
into a DAG of sub-tasks, executes them with the 5-agent team, and
self-corrects across context window resets. Budget guards pause execution
at 90% with a Handoff Report.

### 💬 Adaptive Orchestration
Rony auto-detects when a task exceeds single-agent capability and offers
seamless escalation to the 5-agent team (Planner, Coder, Tester,
Reviewer, Documenter). Complex tasks pause on an escalation gate,
allowing you to choose: [Continue with Rony] or [Escalate to Agent
Console].

### 📦 Zero-Dependency Installer
The Windows installer bundles everything: Python 3.11, Node.js 20, Git,
and Tiktoken BPE cache. Install on a fresh laptop with nothing
pre-installed, and everything works immediately.

### 🔒 Hardened Reliability
All 15 audit findings from the Phase 9 comprehensive codebase audit are
closed with regression tests. Transactional apply/rollback, honest tool
results, authenticated SSE transport, and path containment are now
enforced across all code paths.

### 🎨 Monaco Diff Viewer
Approve edits and see the exact before/after in a Monaco side-by-side
diff viewer with syntax highlighting. Click the Diff button on approval
cards or checkpoint chips.

### 🔄 Live Editor Refresh
File watcher events auto-reload clean tabs within ~1s. Dirty tabs show
a conflict banner with [Reload] / [Keep mine] actions, preserving your
unsaved edits.

## Installation

### Windows
1. Download `CODE OS Setup 5.0.0.exe` (346.7 MB)
2. Run the installer
3. Launch from Start Menu or desktop shortcut
4. No Python, Node, or Git required — everything is bundled

### macOS
1. Download `CODE OS-5.0.0-mac.dmg` (when available)
2. Drag to Applications
3. Right-click → Open (first launch) to bypass Gatekeeper
4. Or run: `xattr -cr /Applications/CODE\ OS.app`

### Linux
Build from source or use the Docker build command in
docs/release-process.md.

## Known Issues
- macOS unsigned builds show "damaged" dialog (workaround: `xattr -cr`)
- Small local models (≤13B) underperform on complex planning
- Linux installers not pre-built (build command provided)

## Feedback
Report issues on GitHub Issues. Pull requests welcome.
