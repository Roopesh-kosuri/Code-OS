import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field
import httpx

from .schemas import MCPServerConfig

logger = logging.getLogger(__name__)

MAX_SCANS_PER_MINUTE = 5


class ValidationResult(BaseModel):
    valid: bool
    error: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class ScanRequest(BaseModel):
    source_type: Literal["github", "json_file", "command_spec", "workspace"]
    target: str
    workspace: Optional[str] = None


class MCPScanner:
    def __init__(self):
        # Rolling scan timestamps per workspace: { workspace_id: [t1, t2, ...] }
        self._scan_history: Dict[str, List[float]] = {}

    def check_rate_limit(self, workspace_key: str) -> bool:
        """Enforce rate limit: max 5 scans per minute per workspace."""
        now = time.time()
        timestamps = self._scan_history.get(workspace_key, [])
        # Keep only scans in the last 60 seconds
        recent = [t for t in timestamps if now - t < 60.0]
        if len(recent) >= MAX_SCANS_PER_MINUTE:
            self._scan_history[workspace_key] = recent
            return False
        recent.append(now)
        self._scan_history[workspace_key] = recent
        return True

    def validate_mcp_config(self, config: MCPServerConfig) -> ValidationResult:
        """Validate discovered MCP server config against security rules (no path traversal, valid strings)."""
        if not config.id or not config.name:
            return ValidationResult(valid=False, error="Server ID and Name are required.")

        if config.type == "stdio":
            cmd = config.command.strip()
            if not cmd:
                return ValidationResult(valid=False, error="Command is required for stdio transport.")

            # Path traversal check on command
            if ".." in cmd or "/" in cmd or "\\" in cmd:
                # Disallow arbitrary path execution unless resolving safe binary
                base_name = os.path.basename(cmd)
                if not base_name:
                    return ValidationResult(valid=False, error="Path traversal or invalid command path detected.")

            # Dangerous shell metacharacters check
            if any(ch in cmd for ch in [";", "&", "|", "`", "$", "(", ")", "<", ">", "\n", "\r"]):
                return ValidationResult(valid=False, error="Command contains dangerous shell metacharacters.")

            if not isinstance(config.args, list) or not all(isinstance(a, str) for a in config.args):
                return ValidationResult(valid=False, error="Arguments must be a list of strings.")

            if not isinstance(config.env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in config.env.items()):
                return ValidationResult(valid=False, error="Environment variables must be string key-value pairs.")

        elif config.type == "http":
            if not config.url:
                return ValidationResult(valid=False, error="URL is required for HTTP transport.")
            try:
                parsed = urlparse(config.url)
                if parsed.scheme not in ["http", "https"]:
                    return ValidationResult(valid=False, error="URL scheme must be http or https.")
            except Exception:
                return ValidationResult(valid=False, error="Invalid URL format.")

        return ValidationResult(valid=True)

    def scan_command_spec(self, spec: str) -> Optional[MCPServerConfig]:
        """Parse command-line spec: 'server-name:command --arg1 --arg2' or 'command --arg1 --arg2'."""
        trimmed = spec.strip()
        if not trimmed:
            return None

        server_name = ""
        cmd_part = trimmed

        if ":" in trimmed and not trimmed.startswith("http://") and not trimmed.startswith("https://"):
            parts = trimmed.split(":", 1)
            server_name = parts[0].strip()
            cmd_part = parts[1].strip()

        tokens = cmd_part.split()
        if not tokens:
            return None

        command = tokens[0]
        args = tokens[1:]
        server_id = server_name.lower().replace(" ", "_") if server_name else command.lower()
        display_name = server_name if server_name else f"{command.capitalize()} MCP"

        cfg = MCPServerConfig(
            id=server_id,
            name=display_name,
            type="stdio",
            command=command,
            args=args,
            enabled=False,
            auto_approve_read_only=True
        )

        validation = self.validate_mcp_config(cfg)
        return cfg if validation.valid else None

    def scan_json_content(self, data: Any) -> List[MCPServerConfig]:
        """Parse MCP server schema from parsed JSON object (e.g. mcpServers or servers list)."""
        configs: List[MCPServerConfig] = []

        if isinstance(data, dict):
            # Check Claude / Cursor style: { "mcpServers": { "<id>": { "command": "...", "args": [...] } } }
            servers_map = data.get("mcpServers") or data.get("servers")
            if isinstance(servers_map, dict):
                for s_id, s_val in servers_map.items():
                    if isinstance(s_val, dict):
                        cmd = s_val.get("command", "")
                        args = s_val.get("args", [])
                        env = s_val.get("env", {})
                        url = s_val.get("url")
                        transport = "http" if url else "stdio"
                        cfg = MCPServerConfig(
                            id=str(s_id),
                            name=s_val.get("name") or f"{s_id.replace('-', ' ').capitalize()}",
                            type=transport,
                            command=cmd,
                            args=[str(a) for a in args] if isinstance(args, list) else [],
                            env={str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {},
                            url=url,
                            enabled=False,
                            auto_approve_read_only=True
                        )
                        if self.validate_mcp_config(cfg).valid:
                            configs.append(cfg)

            # Check direct list: [ { "id": "...", "command": "..." } ]
            elif isinstance(data.get("servers"), list):
                for s_val in data["servers"]:
                    if isinstance(s_val, dict) and "id" in s_val:
                        cfg = MCPServerConfig(**s_val)
                        if self.validate_mcp_config(cfg).valid:
                            configs.append(cfg)

        return configs

    def scan_json_file(self, file_path: str) -> List[MCPServerConfig]:
        """Parse JSON file from workspace or filesystem."""
        path = Path(file_path)
        if not path.is_file():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return self.scan_json_content(data)
        except Exception as exc:
            logger.warning("mcp.scanner failed to parse json file %s: %s", file_path, exc)
            return []

    async def scan_github_repo(self, repo_url: str) -> List[MCPServerConfig]:
        """Scan a GitHub repository README or package.json for MCP server configs (read-only, no auto-exec)."""
        parsed = urlparse(repo_url)
        # SSRF safeguard: only allow github.com
        if parsed.netloc not in ["github.com", "www.github.com"]:
            raise ValueError("Only github.com repositories are supported for MCP scanning.")

        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) < 2:
            raise ValueError("Invalid GitHub repository URL format (expected github.com/owner/repo).")

        owner, repo = path_parts[0], path_parts[1]
        configs: List[MCPServerConfig] = []

        # 1. Probe for package.json
        raw_pkg_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/package.json"
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.get(raw_pkg_url)
                if res.status_code == 200:
                    pkg_data = res.json()
                    pkg_name = pkg_data.get("name", "")
                    if "@modelcontextprotocol" in pkg_name or "mcp" in pkg_name:
                        cfg = MCPServerConfig(
                            id=repo.lower().replace("-", "_"),
                            name=f"{repo.capitalize()} MCP",
                            type="stdio",
                            command="npx",
                            args=["-y", pkg_name],
                            enabled=False,
                            auto_approve_read_only=True
                        )
                        if self.validate_mcp_config(cfg).valid:
                            configs.append(cfg)
        except Exception:
            pass

        # 2. Probe README.md for npx / uvx installation commands
        raw_readme_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/README.md"
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.get(raw_readme_url)
                if res.status_code == 200:
                    readme_text = res.text
                    # Search for npx -y @modelcontextprotocol/... or uvx mcp-server-...
                    npx_matches = re.findall(r"npx\s+-y\s+(@modelcontextprotocol/[\w\-]+)", readme_text)
                    for pkg in set(npx_matches):
                        s_id = pkg.split("/")[-1].replace("server-", "")
                        cfg = MCPServerConfig(
                            id=s_id,
                            name=f"{s_id.capitalize()} MCP",
                            type="stdio",
                            command="npx",
                            args=["-y", pkg],
                            enabled=False,
                            auto_approve_read_only=True
                        )
                        if self.validate_mcp_config(cfg).valid and not any(c.id == cfg.id for c in configs):
                            configs.append(cfg)

                    uvx_matches = re.findall(r"uvx\s+(mcp-server-[\w\-]+)", readme_text)
                    for pkg in set(uvx_matches):
                        s_id = pkg.replace("mcp-server-", "")
                        cfg = MCPServerConfig(
                            id=s_id,
                            name=f"{s_id.capitalize()} MCP",
                            type="stdio",
                            command="uvx",
                            args=[pkg],
                            enabled=False,
                            auto_approve_read_only=True
                        )
                        if self.validate_mcp_config(cfg).valid and not any(c.id == cfg.id for c in configs):
                            configs.append(cfg)
        except Exception:
            pass

        return configs

    def scan_workspace(self, workspace_path: str) -> List[MCPServerConfig]:
        """Auto-discover .mcp.json or .cursor-mcp.json inside workspace directory."""
        configs: List[MCPServerConfig] = []
        ws = Path(workspace_path)
        if not ws.is_dir():
            return configs

        for filename in [".mcp.json", ".cursor-mcp.json", "mcp.json"]:
            candidate = ws / filename
            if candidate.is_file():
                found = self.scan_json_file(str(candidate))
                for f in found:
                    if not any(c.id == f.id for c in configs):
                        configs.append(f)

        return configs


mcp_scanner = MCPScanner()
