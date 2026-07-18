export type WorkspaceDto = {
  path: string;
  name: string;
  last_opened_at: string;
};

export type FileNode = {
  name: string;
  path: string;
  type: "file" | "directory";
  children: FileNode[];
};

export type OpenFile = {
  path: string;
  name: string;
  content: string;
  language: string;
  dirty: boolean;
};

export type ChatMessage = {
  role: "system" | "user" | "assistant";
  content: string;
};

export type ModelDto = {
  name: string;
  provider: string;
  details: Record<string, unknown>;
};

export type GitStatus = {
  branch: string;
  dirty: boolean;
  staged: string[];
  unstaged: string[];
  untracked: string[];
  branches: string[];
};

export type SearchMatch = {
  path: string;
  line: number;
  column: number;
  preview: string;
};

export type TerminalSession = {
  id: string;
  name: string;
  cwd: string;
  shell: string;
};

export type SettingDto = {
  key: string;
  value: string;
};

export type IndexStatus = {
  workspace: string;
  status: "queued" | "indexing" | "ready" | "failed" | string;
  message: string;
  started_at: string | null;
  completed_at: string | null;
  total_files: number;
  indexed_files: number;
  changed_files: number;
  project_type: string;
  language_summary: Record<string, number>;
  frameworks: string[];
  entry_points: string[];
};
