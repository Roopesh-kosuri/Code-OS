import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from .agent_interface import BaseAgent, AgentOutput
from ..service import provider_for
from ..schemas import ChatRequest, ChatMessage
from ....core.paths import normalize_workspace, is_within_workspace

logger = logging.getLogger(__name__)

AUDITOR_SYSTEM_PROMPT = """You are a Principal Security Auditor and Application Security Engineer.
Your task is to conduct a thorough security review of the provided codebase context and static detection findings.

Evaluate the codebase across 5 security domains:
1. Exposed Secrets & Hardcoded Credentials (CWE-798, CWE-259)
2. SQL & Command Injection Vulnerabilities (CWE-89, CWE-78)
3. Input Validation & Sanitization Defects (CWE-20, CWE-116)
4. Resource Exhaustion & Denial of Service Risks (CWE-400, CWE-770)
5. Web Security Deficiencies (XSS, Path Traversal, Insecure Deserialization, Missing Auth/ACLs) (CWE-79, CWE-22, CWE-502, CWE-306)

You MUST return a JSON object matching this structure EXACTLY:
{
  "summary": "Brief 2-3 sentence executive summary of security posture",
  "score": 85,
  "risk_level": "LOW",
  "category_scores": {
    "secrets": 100,
    "injection": 90,
    "validation": 80,
    "resource_limits": 85,
    "auth_web": 80
  },
  "findings": [
    {
      "id": "SEC-01",
      "file": "relative/path/to/file.py",
      "line": 42,
      "severity": "HIGH",
      "category": "injection",
      "cwe_id": "CWE-89",
      "title": "Unparameterized SQL Query",
      "description": "User input is directly concatenated into the SQL statement, allowing arbitrary query manipulation.",
      "fix_suggestion": "Use parameterized queries: cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))",
      "code_snippet": "cursor.execute(f'SELECT * FROM users WHERE id = {user_id}')"
    }
  ]
}

Valid values for risk_level: "CRITICAL", "HIGH", "MEDIUM", "LOW", "CLEAN".
Valid values for severity: "CRITICAL", "HIGH", "MEDIUM", "LOW".
Valid values for category: "secrets", "injection", "validation", "resource_limits", "auth_web".
The score must be an integer between 0 and 100 representing safety/production readiness (100 = completely secure).
Do not include markdown code block syntax outside the JSON object. Return ONLY raw valid JSON.
"""

SECRET_PATTERNS = [
    (re.compile(r'(?i)(api[_-]?key|secret[_-]?key|auth[_-]?token|access[_-]?token)\s*[:=]\s*["\']([a-zA-Z0-9_\-]{16,})["\']'), "Exposed API Key / Secret Token", "CWE-798", "HIGH", "secrets"),
    (re.compile(r'sk-[a-zA-Z0-9]{32,}'), "Exposed OpenAI / API Private Key", "CWE-798", "CRITICAL", "secrets"),
    (re.compile(r'ghp_[a-zA-Z0-9]{36}'), "Exposed GitHub Personal Access Token", "CWE-798", "CRITICAL", "secrets"),
    (re.compile(r'AKIA[0-9A-Z]{16}'), "Exposed AWS Access Key ID", "CWE-798", "CRITICAL", "secrets"),
    (re.compile(r'(?i)(postgres|mysql|mongodb|redis)://[^:]+:[^@]+@'), "Hardcoded Database Credentials URI", "CWE-259", "CRITICAL", "secrets"),
]

INJECTION_PATTERNS = [
    (re.compile(r'(?i)(execute|query|raw)\s*\(\s*f["\'].*\{.*\}'), "Unparameterized String Interpolated Database Query", "CWE-89", "CRITICAL", "injection"),
    (re.compile(r'(?i)(execute|query|raw)\s*\(\s*["\'].*\%\s*\(|\s*\+\s*'), "String Concatenated SQL Statement", "CWE-89", "HIGH", "injection"),
    (re.compile(r'(?i)(os\.system|subprocess\.Popen|subprocess\.run)\s*\(\s*f["\'].*\{.*\}'), "Command Injection via Formatted Shell Execution", "CWE-78", "CRITICAL", "injection"),
    (re.compile(r'eval\s*\(\s*'), "Dangerous Dynamic Code Evaluation (eval)", "CWE-95", "CRITICAL", "injection"),
    (re.compile(r'exec\s*\(\s*'), "Dangerous Dynamic Execution (exec)", "CWE-95", "HIGH", "injection"),
]

RESOURCE_PATTERNS = [
    (re.compile(r'while\s+True\s*:'), "Unbounded Infinite Loop", "CWE-835", "MEDIUM", "resource_limits"),
    (re.compile(r'pickle\.loads?\s*\('), "Insecure Object Deserialization (pickle)", "CWE-502", "CRITICAL", "auth_web"),
    (re.compile(r'yaml\.unsafe_load\s*\('), "Insecure Unsafe YAML Deserialization", "CWE-502", "HIGH", "auth_web"),
    (re.compile(r'dangerouslySetInnerHTML\s*='), "Raw HTML Injection (Potential React XSS)", "CWE-79", "MEDIUM", "auth_web"),
]


class AuditorAgent(BaseAgent):
    """Specialized agent for security & production-readiness auditing."""

    def __init__(self, provider_config: Optional[dict] = None) -> None:
        super().__init__("Code Verification Agent", provider_config=provider_config)

    def get_system_prompt(self) -> str:
        return AUDITOR_SYSTEM_PROMPT

    def _static_scan_workspace(self, workspace_path: Path, max_files: int = 150) -> list[dict]:
        """Pass 1: Static Pattern & Secret Detector."""
        findings = []
        file_count = 0
        finding_counter = 1

        ignore_dirs = {".git", "node_modules", "dist", "build", "dist-electron", ".venv", "__pycache__", ".idea", ".vscode"}
        ignore_exts = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".zip", ".tar", ".gz", ".pdf", ".exe", ".dll", ".so", ".dylib", ".pyc", ".db", ".sqlite"}

        for path in workspace_path.rglob("*"):
            if file_count >= max_files:
                break
            if any(part in ignore_dirs for part in path.parts):
                continue
            if not path.is_file() or path.suffix.lower() in ignore_exts:
                continue

            rel_display = str(path.relative_to(workspace_path))

            # Check unignored .env files
            if path.name.startswith(".env") and not path.name.endswith(".example"):
                findings.append({
                    "id": f"STATIC-{finding_counter}",
                    "file": rel_display,
                    "line": 1,
                    "severity": "HIGH",
                    "category": "secrets",
                    "cwe_id": "CWE-526",
                    "title": "Environment Secrets File (.env) in Repository",
                    "description": "Environment variable configuration file (.env) detected in workspace. Sensitive keys may be accidentally committed.",
                    "fix_suggestion": "Add .env to .gitignore and use environment secret managers for production deployment.",
                    "code_snippet": f"File: {path.name}"
                })
                finding_counter += 1

            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            file_count += 1
            lines = content.splitlines()

            # Scan lines against pattern sets
            for line_idx, line in enumerate(lines, 1):
                if len(line) > 1000:  # Skip minified bundle lines
                    continue

                for pattern, title, cwe, severity, category in SECRET_PATTERNS + INJECTION_PATTERNS + RESOURCE_PATTERNS:
                    if pattern.search(line):
                        findings.append({
                            "id": f"STATIC-{finding_counter}",
                            "file": rel_display,
                            "line": line_idx,
                            "severity": severity,
                            "category": category,
                            "cwe_id": cwe,
                            "title": title,
                            "description": f"Potential {title.lower()} detected on line {line_idx}.",
                            "fix_suggestion": "Review finding and parameterize/sanitize inputs or move hardcoded credentials to safe environment variables.",
                            "code_snippet": line.strip()[:150]
                        })
                        finding_counter += 1
                        if len(findings) >= 50:
                            break
                if len(findings) >= 50:
                    break

        return findings

    async def execute_audit(self, workspace: str, provider_config: Optional[dict] = None) -> dict:
        """Run multi-pass security audit of workspace."""
        if provider_config:
            self.provider_config = provider_config

        start_time = time.time()
        ws_path = normalize_workspace(workspace)

        # ── Pass 1: Static Pattern Scan ───────────────────────────────────────
        static_findings = self._static_scan_workspace(ws_path)

        # ── Pass 2: High-Risk Code Snippet Grounding ──────────────────────────
        # Gather top relevant code files for LLM security analysis
        source_snippets = []
        files_to_read = list({f["file"] for f in static_findings[:10]})
        
        # If static scan found few files, pick key entrypoints
        if len(files_to_read) < 5:
            for candidate in ["src/main.ts", "src/App.tsx", "backend/app/main.py", "main.py", "app.py", "server.js"]:
                p = ws_path / candidate
                if p.exists() and candidate not in files_to_read:
                    files_to_read.append(candidate)

        for rel in files_to_read[:8]:
            p = ws_path / rel
            if p.is_file():
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")[:3000]
                    source_snippets.append(f"File: {rel}\n```\n{text}\n```")
                except OSError:
                    continue

        grounded_context = "\n\n".join(source_snippets) if source_snippets else "(no primary source files found)"
        static_summary = json.dumps(static_findings[:15], indent=2)

        # ── Pass 3: Multi-Model LLM Security Audit ────────────────────────────
        user_prompt = (
            f"Workspace Path: {workspace}\n\n"
            f"=== STATIC SCAN INDICATORS ===\n{static_summary}\n\n"
            f"=== GROUNDED SOURCE SNIPPETS ===\n{grounded_context}"
        )

        chat_req = self.create_chat_request(
            messages=[
                ChatMessage(role="system", content=AUDITOR_SYSTEM_PROMPT),
                ChatMessage(role="user", content=user_prompt)
            ]
        )

        llm_findings = []
        summary = "Security audit completed."
        llm_score = 100
        risk_level = "CLEAN"
        category_scores = {"secrets": 100, "injection": 100, "validation": 100, "resource_limits": 100, "auth_web": 100}

        try:
            provider = await provider_for(chat_req)
            tokens = []
            async for token in provider.stream_chat(chat_req.model, chat_req.messages, temperature=0.1):
                tokens.append(token)
            raw_response = "".join(tokens).strip()

            from ...duo.service import _extract_json
            parsed = _extract_json(raw_response)
            if isinstance(parsed, dict):
                summary = parsed.get("summary", summary)
                llm_score = int(parsed.get("score", 100))
                risk_level = str(parsed.get("risk_level", "LOW")).upper()
                category_scores = parsed.get("category_scores", category_scores)
                llm_findings = parsed.get("findings", [])
        except Exception as exc:
            logger.warning("AuditorAgent LLM pass encountered error: %s. Using static findings.", exc)
            summary = f"Static analysis completed ({len(static_findings)} potential indicators found)."

        # ── Merge & Deduplicate Findings ──────────────────────────────────────
        all_findings = list(llm_findings)
        seen_keys = {(f.get("file"), f.get("line"), f.get("title")) for f in all_findings}

        for sf in static_findings:
            key = (sf.get("file"), sf.get("line"), sf.get("title"))
            if key not in seen_keys:
                all_findings.append(sf)
                seen_keys.add(key)

        # ── Calculate Final Weighted Score ────────────────────────────────────
        sev_deductions = {"CRITICAL": 25, "HIGH": 15, "MEDIUM": 8, "LOW": 3}
        total_deduction = sum(sev_deductions.get(f.get("severity", "LOW").upper(), 5) for f in all_findings[:10])
        final_score = max(0, min(100, min(llm_score, 100 - total_deduction)))

        if final_score >= 90:
            final_risk = "CLEAN"
        elif final_score >= 75:
            final_risk = "LOW"
        elif final_score >= 50:
            final_risk = "MEDIUM"
        elif final_score >= 25:
            final_risk = "HIGH"
        else:
            final_risk = "CRITICAL"

        duration = round(time.time() - start_time, 2)

        return {
            "summary": summary,
            "score": final_score,
            "risk_level": final_risk,
            "duration": duration,
            "files_analyzed": len(files_to_read),
            "category_scores": category_scores,
            "findings": all_findings,
            "model_used": chat_req.model or "local-static",
            "provider_used": chat_req.provider or "static"
        }

    async def execute(self, job_id: str, task_id: str, title: str, context: str, workspace: str) -> AgentOutput:
        report = await self.execute_audit(workspace)
        return AgentOutput(
            agent_role=self.role,
            task_id=task_id,
            status="success",
            confidence=0.9,
            reasoning_summary=f"Security audit score: {report['score']}/100 ({report['risk_level']})",
            logs=[f"Completed security audit in {report['duration']}s. Found {len(report['findings'])} items."],
            structured_data=report
        )
