/skill:python-engineering

## Task: Write the shared foundation modules

Read `SPEC.md` and `CLAUDE.md` in this directory before writing anything.

### Files to create

**`/root/challenge/exceptions.py`**  
**`/root/challenge/models.py`**  
**`/root/challenge/agents/__init__.py`**

### Exact content

Write these files exactly as specified in `CLAUDE.md` under "Canonical shared
definitions". Do not deviate. Other modules import from these; divergence breaks
the entire project.

#### exceptions.py

Five exception classes in a single hierarchy:
- `MASPError(Exception)` — base
- `OrchestratorError(MASPError)` — raised by Orchestrator for fatal run failures
- `SubAgentError(MASPError)` — raised internally by sub-agents, never propagates past Orchestrator
- `ToolError(MASPError)` — raised by tool functions, never propagates past sub-agents
- `LLMError(MASPError)` — raised by LLMClient, never propagates past the calling component

Each class: one-line docstring stating its purpose. No fields beyond the message.

#### models.py

Three dataclasses, exactly as in `CLAUDE.md`:

`ToolOutput`:
- `tool_name: str`
- `status: Literal["ok", "error"]`
- `summary: str`
- `__repr__` showing tool_name and status

`SubAgentResult`:
- `agent_id: str` — UUID v4 string
- `agent_type: Literal["secrets", "ports", "env", "config"]`
- `status: Literal["complete", "partial", "failed"]`
- `findings: list[str]` — default empty list
- `severity: Literal["Critical", "High", "Medium", "Low", "Info"]`
- `tool_outputs: list[ToolOutput]` — default empty list
- `error: str | None` — null iff status is "complete"
- `__repr__` showing agent_type, status, severity, count of findings

`AuditTrailEntry`:
- `ts: str` — ISO 8601 UTC timestamp
- `event_type: str`
- `agent_id: str | None`
- `agent_type: str | None`
- `payload: dict`

Add a module-level `to_jsonl_line(entry: AuditTrailEntry) -> str` function that
serialises an entry to a JSON string (no trailing newline). Use `json.dumps` with
`ensure_ascii=False`. This is the only serialisation path for trail entries.

#### agents/__init__.py

Empty file. Just creates the package.

### Constraints

- No imports beyond stdlib (`dataclasses`, `typing`, `json`).
- `models.py` MUST NOT import from `exceptions.py` or any project module.
- `exceptions.py` MUST NOT import from any project module.
- Run `python -c "from models import SubAgentResult, ToolOutput, AuditTrailEntry; from exceptions import OrchestratorError, LLMError, ToolError, SubAgentError"` from `/root/challenge/` to verify imports work before finishing.
