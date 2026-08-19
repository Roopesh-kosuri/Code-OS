import { debugClient } from "../debug/debugClient";

/** Adds debugger-only Monaco decorations without altering editor configuration. */
export function installDebugDecorations(editor: any, monaco: any, filePath: string) {
  const decorations = editor.createDecorationsCollection([]);
  const margin = editor.onMouseDown((event: any) => {
    if (event.target.type === monaco.editor.MouseTargetType.GUTTER_LINE_NUMBERS && event.target.position) {
      debugClient.toggleBreakpoint(filePath, event.target.position.lineNumber);
    }
  });
  const unsubscribe = debugClient.subscribe((state) => {
    const items: any[] = (state.breakpoints[filePath] ?? []).map((line) => ({ range: new monaco.Range(line, 1, line, 1), options: { isWholeLine: true, linesDecorationsClassName: "code-os-breakpoint" } }));
    if (state.execution?.filePath === filePath) items.push({ range: new monaco.Range(state.execution.line, 1, state.execution.line, 1), options: { isWholeLine: true, className: "code-os-debug-line" } });
    decorations.set(items);
  });
  const dispose = () => { margin.dispose(); decorations.clear(); unsubscribe(); };
  editor.onDidDispose(dispose);
  return dispose;
}
