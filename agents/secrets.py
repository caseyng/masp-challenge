from __future__ import annotations

import asyncio
from collections import defaultdict

from agents.base import BaseSubAgent
from exceptions import LLMError, ToolError
from llm_client import LLMClient
from models import SubAgentResult, ToolOutput
from tools import scan_filesystem_for_secrets

SYSTEM_PROMPT = """You are a security analyst reviewing filesystem scan results for a secrets audit.

You will be given a list of pattern matches found in source files. Each match includes
the file path, line number, and pattern category — but NOT the actual secret value.

Your task:
1. Assess the severity of the findings: Critical, High, Medium, Low, or Info.
   - Critical: active credentials, private keys in tracked files
   - High: likely real credentials, API keys
   - Medium: placeholder-looking but suspicious patterns
   - Low: commented-out or example values
   - Info: no findings or clearly test/example data
2. List the key findings as bullet points (file paths and pattern types only).
3. End your response with a line: SEVERITY: <label>

Be concise. Do not reproduce secret values."""


def _parse_response(text: str) -> tuple[list[str], str]:
    lines = [l for l in text.strip().splitlines() if l.strip()]
    severity = "Medium"
    findings = []
    for line in reversed(lines):
        if line.strip().upper().startswith("SEVERITY:"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                candidate = parts[1].strip().capitalize()
                if candidate in ("Critical", "High", "Medium", "Low", "Info"):
                    severity = candidate
            break
    for line in lines:
        if line.strip().upper().startswith("SEVERITY:"):
            break
        if line.strip():
            findings.append(line.strip())
    return findings, severity


class SecretsSubAgent(BaseSubAgent):
    async def run(self) -> SubAgentResult:
        await super().run()
        return await self._execute()

    async def _execute(self) -> SubAgentResult:
        tool_outputs: list[ToolOutput] = []
        matches: list[dict] = []
        tool_ok = True

        try:
            matches = await asyncio.to_thread(scan_filesystem_for_secrets, ".")
            n_files = len({m["file"] for m in matches})
            tool_outputs.append(ToolOutput(
                tool_name="scan_filesystem_for_secrets",
                status="ok",
                summary=f"Found {len(matches)} pattern matches across {n_files} files",
            ))
        except ToolError as exc:
            tool_ok = False
            tool_outputs.append(ToolOutput(
                tool_name="scan_filesystem_for_secrets",
                status="error",
                summary=str(exc),
            ))

        if tool_ok and matches:
            sample = matches[:20]
            lines = [f"- {m['file']}:{m['line_number']} [{m['pattern_category']}]" for m in sample]
            if len(matches) > 20:
                by_cat: dict[str, int] = defaultdict(int)
                for m in matches:
                    by_cat[m["pattern_category"]] += 1
                summary_line = "Summary: " + ", ".join(f"{cat}={cnt}" for cat, cnt in by_cat.items())
                lines.append(summary_line)
            user_msg = (
                f"Request: {self._audit_request}\n\n"
                f"Filesystem scan found {len(matches)} matches:\n" + "\n".join(lines)
            )
        elif not tool_ok:
            user_msg = f"Request: {self._audit_request}\n\nFilesystem scan failed; no results available."
        else:
            user_msg = f"Request: {self._audit_request}\n\nFilesystem scan found no matches."

        try:
            response = LLMClient().call(system=SYSTEM_PROMPT, user=user_msg)
            findings, severity = _parse_response(response)
            status = "complete"
        except LLMError:
            by_cat: dict[str, int] = defaultdict(int)
            for m in matches:
                by_cat[m["pattern_category"]] += 1
            findings = [
                f"Found {cnt} matches for pattern: {cat} in {len({x['file'] for x in matches if x['pattern_category'] == cat})} files"
                for cat, cnt in by_cat.items()
            ] or ["Scan returned no matches."]
            severity = "Medium"
            status = "partial"

        return SubAgentResult(
            agent_id=self._agent_id,
            agent_type="secrets",
            status=status,
            findings=findings,
            severity=severity,  # type: ignore[arg-type]
            tool_outputs=tool_outputs,
            error=None if status == "complete" else "LLM call failed",
        )
