from __future__ import annotations

import asyncio
from collections import defaultdict

from agents.base import BaseSubAgent
from exceptions import LLMError, ToolError
from llm_client import LLMClient
from models import SubAgentResult, ToolOutput
from tools import scan_config_files

SYSTEM_PROMPT = """You are a security analyst reviewing configuration file issues.

You will receive a list of configuration problems found in YAML, JSON, INI, and .env
files. Each entry includes the file path, the configuration key, and the type of issue.
Values are NOT provided.

Your task:
1. Assess the overall security severity: Critical, High, Medium, Low, or Info.
   - Critical: TLS disabled, plaintext credentials in tracked config
   - High: debug mode in a config that looks production-like, bind-all interfaces
   - Medium: multiple debug/insecure settings across configs
   - Low: minor issues in example/test files
   - Info: no issues found
2. List key findings as bullet points (file, key, issue).
3. End with: SEVERITY: <label>"""


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


class ConfigSubAgent(BaseSubAgent):
    async def run(self) -> SubAgentResult:
        await super().run()
        return await self._execute()

    async def _execute(self) -> SubAgentResult:
        tool_outputs: list[ToolOutput] = []
        issues: list[dict] = []

        try:
            issues = await asyncio.to_thread(scan_config_files, ".")
            n_files = len({i["file"] for i in issues})
            tool_outputs.append(ToolOutput(
                tool_name="scan_config_files",
                status="ok",
                summary=f"{len(issues)} configuration issues found across {n_files} files",
            ))
        except ToolError as exc:
            tool_outputs.append(ToolOutput(
                tool_name="scan_config_files",
                status="error",
                summary=str(exc),
            ))

        if issues:
            lines = [f"- {i['file']}: {i['key']} — {i['issue']}" for i in issues]
            user_msg = (
                f"Request: {self._audit_request}\n\n"
                f"Configuration issues found:\n" + "\n".join(lines)
            )
        else:
            user_msg = f"Request: {self._audit_request}\n\nNo configuration issues found."

        try:
            response = LLMClient().call(system=SYSTEM_PROMPT, user=user_msg)
            findings, severity = _parse_response(response)
            status = "complete"
        except LLMError:
            findings = [f"{i['file']}: {i['key']} — {i['issue']}" for i in issues] or ["No configuration issues found."]
            severity = "Medium"
            status = "partial"

        return SubAgentResult(
            agent_id=self._agent_id,
            agent_type="config",
            status=status,
            findings=findings,
            severity=severity,  # type: ignore[arg-type]
            tool_outputs=tool_outputs,
            error=None if status == "complete" else "LLM call failed",
        )
