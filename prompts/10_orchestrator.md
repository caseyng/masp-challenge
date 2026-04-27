/skill:python-engineering

## Task: Implement Orchestrator

Read `SPEC.md` in full — especially §5 (Orchestrator contract), §6 (lifecycle),
§7 (all failure modes), §10 (atomicity), §11 (ordering), §12 (interaction
contracts), §13 (concurrency), §17 (error propagation) — and `CLAUDE.md` before
writing.

### File to create

**`/root/challenge/orchestrator.py`**

### Existing files to read first

- `exceptions.py`
- `models.py`
- `trail_writer.py` — AuditTrailWriter
- `llm_client.py` — LLMClient
- `agents/secrets.py`, `agents/ports.py`, `agents/env.py`, `agents/config.py`

### Class: Orchestrator

```python
class Orchestrator:
    async def run(self, audit_request: str) -> None:
```

`run()` MUST NOT be called more than once per instance. Second call raises
`OrchestratorError("double_run")`.

---

### Step-by-step implementation of `run()`

Follow SPEC.md §11 ordering exactly:

#### Step 1: Validate inputs

```python
api_key_present = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"))
request_valid = bool(audit_request and audit_request.strip() and len(audit_request) <= 2000)
```

If either check fails: raise `OrchestratorError` with a descriptive message.
Do NOT create any files before this check passes.

#### Step 2: Open AuditTrailWriter

```python
writer = AuditTrailWriter()
writer.open("audit_trail.jsonl")
```

If `open()` raises: re-raise as `OrchestratorError`.

#### Step 3: Append `run_start`

```python
writer.append(AuditTrailEntry(
    ts=now_utc(),
    event_type="run_start",
    agent_id=None,
    agent_type=None,
    payload={"request": audit_request},
))
```

Provide a helper `now_utc() -> str` that returns an ISO 8601 UTC string:
```python
from datetime import datetime, timezone
def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
```

#### Step 4: LLM decomposition

Call `LLMClient().call(system=DECOMPOSE_SYSTEM, user=audit_request)`.

```python
DECOMPOSE_SYSTEM = """You are a security audit orchestrator. Given a security audit request,
select the most relevant specialist agents to run from this closed list:
- secrets: scan filesystem for committed secrets and API keys
- ports: probe localhost for exposed network services
- env: inspect environment variables for sensitive names
- config: scan configuration files for insecure settings

Respond with a JSON array of agent type strings, e.g.: ["secrets", "ports", "env"]
Select 2 to 4 agents. Only use types from the list above. No explanation needed."""
```

Parse the response as JSON. Extract any values that are in `{"secrets","ports","env","config"}`.
Clamp to [2,4]:
- If fewer than 2 valid types after filtering: use all 4 types.
- If more than 4: take the first 4.

If the LLM call raises `LLMError`: fall back to all 4 types. Append an `llm_call` trail entry with `status: "error"`.

Append `decomposition` trail entry:
```python
writer.append(AuditTrailEntry(
    ts=now_utc(), event_type="decomposition",
    agent_id=None, agent_type=None,
    payload={"subtasks": selected_types},
))
```

#### Step 5: Create sub-agent instances

```python
AGENT_REGISTRY = {
    "secrets": SecretsSubAgent,
    "ports": PortsSubAgent,
    "env": EnvSubAgent,
    "config": ConfigSubAgent,
}
```

For each selected type, create an instance:
```python
agent_id = str(uuid.uuid4())
agent = AGENT_REGISTRY[agent_type](agent_id, agent_type, audit_request)
```

Append `agent_start` entry for each agent before launching.

#### Step 6: Run all sub-agents concurrently with recovery

Use `asyncio.gather()` with a per-agent wrapper that handles recovery.

**Per-agent wrapper** (`_run_with_recovery`):

```python
async def _run_with_recovery(
    self, agent, writer: AuditTrailWriter
) -> SubAgentResult:
```

Logic:
1. Try `asyncio.wait_for(agent.run(), timeout=timeout_secs)`.
2. On success: append `agent_end` trail entry. Return result.
3. On `asyncio.TimeoutError` or any `Exception`:
   - Append `agent_retry` trail entry with reason.
   - Create a NEW instance of the same agent type with the same `agent_id` + `audit_request`.
   - Try `asyncio.wait_for(new_agent.run(), timeout=timeout_secs)` once more.
   - On success: append `agent_end`. Return result.
   - On second failure: append `agent_recovery` trail entry. Return `agent._graceful_partial(reason)`.

Read `MASP_TIMEOUT_SECS` from env (default `45`).

Append `tool_call` trail entries from `result.tool_outputs` after each agent completes.

#### Step 7: Append per-agent llm_call trail entries

For each result, append one `llm_call` entry:
```python
AuditTrailEntry(
    ts=now_utc(), event_type="llm_call",
    agent_id=result.agent_id, agent_type=result.agent_type,
    payload={"purpose": "reasoning", "status": result.status if result.status != "failed" else "error"},
)
```

#### Step 8: LLM synthesis

Build a clean synthesis input from all SubAgentResults. Pass ONLY:
- Agent type, status, severity, and findings list.
- Do NOT pass tool_outputs or raw scan data.

```python
SYNTHESISE_SYSTEM = """You are a security audit lead synthesising findings from specialist agents.

You will receive structured findings from multiple security sub-agents. Each entry includes
the agent type, completion status, severity rating, and key findings.

Write an executive summary (2-3 paragraphs) that:
1. States the overall security posture and most critical concerns.
2. Highlights the top 3 actionable recommendations.
3. Notes any agents that did not complete and what that means for coverage.

Be direct and actionable. Address a technical security lead."""
```

User message format:
```
Audit request: {audit_request}

Agent findings:
{for each result: "## {agent_type} ({status}, severity={severity})\n{findings as bullets}"}
```

On `LLMError`: use the fallback summary:
```
"Synthesis unavailable — LLM call failed. See individual agent sections for findings."
```

Append `synthesis` trail entry.

#### Step 9: Write `report.md`

Write `report.md` to CWD with UTF-8 encoding. Structure per SPEC.md §4:

```markdown
# Security Audit Report

**Request:** {audit_request}

## Executive Summary

{executive_summary}

## {AgentType} Findings

**Severity:** {severity}
**Status:** {status}

{findings as bullet list}

[...one section per agent...]

## Audit Metadata

- **Total duration:** {duration:.1f}s
- **Sub-agents run:** {n}
- **Sub-agents failed:** {n_failed}
- **Timestamp:** {now_utc()}
```

If the write raises: raise `OrchestratorError`.

#### Step 10: Append `run_end` and close

```python
writer.append(AuditTrailEntry(
    ts=now_utc(), event_type="run_end",
    agent_id=None, agent_type=None,
    payload={
        "duration_seconds": round(time.time() - start_time, 2),
        "exit_code": 0,
    },
))
writer.close()
```

**ALWAYS** append `run_end` and close the writer, even if intermediate steps fail.
Use a `try/finally` block to guarantee this.

---

### Error propagation (SPEC.md §17)

| Failure | Action |
|---|---|
| `OrchestratorError` from validation or file write | Re-raise; caller exits 1 |
| `LLMError` from decompose | Fall back to all 4 types; continue |
| `LLMError` from synthesise | Use fallback summary; continue; exit 0 |
| All sub-agents return `status: "failed"` | Continue; report documents failures; exit 0 |

---

### Imports

```python
import asyncio, os, time, uuid, json
from datetime import datetime, timezone
from exceptions import OrchestratorError, LLMError
from models import SubAgentResult, AuditTrailEntry, ToolOutput
from trail_writer import AuditTrailWriter
from llm_client import LLMClient
from agents.secrets import SecretsSubAgent
from agents.ports import PortsSubAgent
from agents.env import EnvSubAgent
from agents.config import ConfigSubAgent
```

### Verify

```bash
cd /root/challenge && python -c "from orchestrator import Orchestrator; print('import ok')"
```
