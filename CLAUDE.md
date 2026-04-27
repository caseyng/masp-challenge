# MASP Implementation Harness

## Authority

`SPEC.md` in this directory is the implementation authority. Every behavioural
decision MUST be traceable to a section in SPEC.md. If SPEC.md and this file
conflict, SPEC.md wins.

## Project layout — write files exactly here

```
/root/challenge/
  exceptions.py          ← custom exception hierarchy
  models.py              ← SubAgentResult, ToolOutput, AuditTrailEntry dataclasses
  trail_writer.py        ← AuditTrailWriter
  llm_client.py          ← LLMClient (wraps Anthropic or OpenAI SDK)
  tools.py               ← 4 stateless tool functions
  orchestrator.py        ← Orchestrator
  main.py                ← CLI entry point
  requirements.txt
  agents/
    __init__.py          ← empty
    base.py              ← BaseSubAgent ABC
    secrets.py           ← SecretsSubAgent
    ports.py             ← PortsSubAgent
    env.py               ← EnvSubAgent
    config.py            ← ConfigSubAgent
  fixtures/
    .env.example
    config.yaml
    dummy_private_key.pem
    settings.json
```

## Canonical shared definitions — use exactly these

These definitions are shared across all modules. Do NOT redefine them.

### exceptions.py

```python
class MASPError(Exception):
    pass

class OrchestratorError(MASPError):
    pass

class SubAgentError(MASPError):
    pass

class ToolError(MASPError):
    pass

class LLMError(MASPError):
    pass
```

### models.py

```python
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class ToolOutput:
    tool_name: str
    status: Literal["ok", "error"]
    summary: str

    def __repr__(self) -> str:
        return f"ToolOutput(tool={self.tool_name!r}, status={self.status!r})"

@dataclass
class SubAgentResult:
    agent_id: str
    agent_type: Literal["secrets", "ports", "env", "config"]
    status: Literal["complete", "partial", "failed"]
    findings: list[str]
    severity: Literal["Critical", "High", "Medium", "Low", "Info"]
    tool_outputs: list[ToolOutput]
    error: str | None

    def __repr__(self) -> str:
        return (
            f"SubAgentResult(agent_type={self.agent_type!r}, "
            f"status={self.status!r}, severity={self.severity!r}, "
            f"findings={len(self.findings)})"
        )

@dataclass
class AuditTrailEntry:
    ts: str          # ISO 8601 UTC, e.g. "2026-04-27T10:00:00.123Z"
    event_type: str  # closed set per SPEC.md §4
    agent_id: str | None
    agent_type: str | None
    payload: dict
```

## Implementation rules (non-negotiable)

1. **Python 3.11+.** Use `X | None`, `match/case`, `asyncio` throughout.
2. **No LangChain, LangGraph, or agent frameworks.** Raw SDK calls only.
3. **Anthropic SDK takes precedence** when `ANTHROPIC_API_KEY` is set. OpenAI SDK
   is fallback when only `OPENAI_API_KEY` is set.
4. **All file I/O uses `encoding="utf-8"` explicitly.**
5. **All external calls (LLM, socket) have explicit timeouts.** No call without a timeout.
6. **No secret values in any output.** Env var values, regex match content, and file
   contents MUST NOT appear in `audit_trail.jsonl`, `report.md`, or LLM prompts.
   Only: file paths, env var names, pattern category names, port numbers.
7. **Sub-agents are async coroutines.** `run()` is `async def`.
8. **Tools are synchronous functions.** Called with `asyncio.to_thread()` or directly
   inside the sub-agent coroutine.
9. **`audit_trail.jsonl` is written incrementally** — one flush per `append()` call.
10. **`report.md` is written once** at end of orchestration.
11. **The overall run MUST exit 0** even when all sub-agents fail. Exit 1 only on
    `OrchestratorError`.

## Dependency waves — submit prompts in this order

```
Wave 0 (first):  prompts/00_foundations.md   → exceptions.py, models.py, agents/__init__.py
Wave 1 (parallel after Wave 0):
                 prompts/01_trail_writer.md   → trail_writer.py
                 prompts/02_llm_client.md     → llm_client.py
                 prompts/03_tools.md          → tools.py
                 prompts/04_fixtures.md       → fixtures/
Wave 2 (after Wave 1):
                 prompts/05_base_agent.md     → agents/base.py
Wave 3 (parallel after Wave 2):
                 prompts/06_secrets_agent.md  → agents/secrets.py
                 prompts/07_ports_agent.md    → agents/ports.py
                 prompts/08_env_agent.md      → agents/env.py
                 prompts/09_config_agent.md   → agents/config.py
Wave 4 (after Wave 3):
                 prompts/10_orchestrator.md   → orchestrator.py
Wave 5 (after Wave 4):
                 prompts/11_main.md           → main.py, requirements.txt
```
