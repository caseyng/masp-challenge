from __future__ import annotations

import asyncio

from agents.base import BaseSubAgent
from exceptions import LLMError, ToolError
from llm_client import LLMClient
from models import SubAgentResult, ToolOutput
from tools import inspect_environment_variables

SYSTEM_PROMPT = """You are a security analyst reviewing environment variable names for a running process.

You will receive a list of environment variable names that match sensitive patterns
(e.g. names containing KEY, SECRET, TOKEN, PASSWORD). Values are NOT provided.

Your task:
1. Assess risk of having sensitive variables in the process environment.
   - Critical: credentials or keys for production systems likely exposed
   - High: multiple credential-type variables present
   - Medium: some sensitive-looking variables; context unclear
   - Low: few or expected variables (e.g. only PATH-like)
   - Info: no sensitive variable names found
2. List findings as bullet points naming the variable name and concern.
3. End with: SEVERITY: <label>

Do not guess at values. Assess based on names alone."""


def _parse_response(text: str) -> tuple[list[str], str]:
    lines = [l for l in text.strip().splitlines() if l.strip()]
    severity = "Low"
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


class EnvSubAgent(BaseSubAgent):
    async def run(self) -> SubAgentResult:
        await super().run()
        return await self._execute()

    async def _execute(self) -> SubAgentResult:
        tool_outputs: list[ToolOutput] = []
        env_results: list[dict] = []

        try:
            env_results = await asyncio.to_thread(inspect_environment_variables)
            tool_outputs.append(ToolOutput(
                tool_name="inspect_environment_variables",
                status="ok",
                summary=f"{len(env_results)} sensitive env var names found",
            ))
        except ToolError as exc:
            tool_outputs.append(ToolOutput(
                tool_name="inspect_environment_variables",
                status="error",
                summary=str(exc),
            ))

        if env_results:
            lines = [f"- {r['name']} ({r['sensitivity_hint']})" for r in env_results]
            user_msg = (
                f"Request: {self._audit_request}\n\n"
                f"Sensitive environment variable names found:\n" + "\n".join(lines)
            )
        else:
            user_msg = f"Request: {self._audit_request}\n\nNo sensitive environment variable names found."

        try:
            response = LLMClient().call(system=SYSTEM_PROMPT, user=user_msg)
            findings, severity = _parse_response(response)
            status = "complete"
        except LLMError:
            findings = [f"Sensitive env var name present: {r['name']}" for r in env_results] or ["No sensitive env var names found."]
            severity = "Medium"
            status = "partial"

        return SubAgentResult(
            agent_id=self._agent_id,
            agent_type="env",
            status=status,
            findings=findings,
            severity=severity,  # type: ignore[arg-type]
            tool_outputs=tool_outputs,
            error=None if status == "complete" else "LLM call failed",
        )
