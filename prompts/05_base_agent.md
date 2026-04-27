/skill:python-engineering

## Task: Implement BaseSubAgent

Read `SPEC.md` (§2b Architectural Constraints, §5 Component Contracts —
BaseSubAgent, §6 Lifecycle, §7 failure modes) and `CLAUDE.md` before writing.

### File to create

**`/root/challenge/agents/base.py`**

### What this component does

`BaseSubAgent` is an abstract base class. All four specialist sub-agents extend it.
It cannot be instantiated directly. It enforces the sub-agent lifecycle, owns the
`agent_id`, and defines the abstract `run()` coroutine that specialists must override.

### Lifecycle (SPEC.md §6)

```
CONSTRUCTED → run() called → EXECUTING → RETURNED
```

Calling `run()` a second time (in RETURNED state) raises `SubAgentError("already_run")`.

### Constructor

```python
def __init__(self, agent_id: str, agent_type: str, audit_request: str) -> None:
```

- `agent_id`: UUID v4 string. MUST NOT change after construction.
- `agent_type`: one of `"secrets"`, `"ports"`, `"env"`, `"config"`.
- `audit_request`: the original free-text request from the CLI. Passed to the LLM
  as user context for reasoning. MUST NOT be modified or stored beyond the instance.

### Abstract method

```python
@abstractmethod
async def run(self) -> SubAgentResult:
```

This is an async coroutine. Specialists override it.

### State guard

`BaseSubAgent` tracks `_executed: bool` (starts `False`). At the start of `run()`,
if `_executed` is `True`, raise `SubAgentError("already_run")`. Set `_executed = True`
before doing any work.

### `__repr__`

`BaseSubAgent(agent_id='...', agent_type='...', executed=True|False)`

### Helper: `_graceful_partial`

Provide a protected helper method that specialists can call to produce a graceful
partial result (used when the sub-agent cannot complete):

```python
def _graceful_partial(self, reason: str) -> SubAgentResult:
```

Returns a `SubAgentResult` with:
- `agent_id` = this instance's agent_id
- `agent_type` = this instance's agent_type
- `status = "failed"`
- `findings = [f"Sub-agent did not complete: {reason}"]`
- `severity = "Info"`
- `tool_outputs = []`
- `error = reason`

### Imports available

```python
from abc import ABC, abstractmethod
from models import SubAgentResult, ToolOutput
from exceptions import SubAgentError
```

### Verify

After writing, run:
```bash
cd /root/challenge && python -c "
from agents.base import BaseSubAgent
from models import SubAgentResult

class TestAgent(BaseSubAgent):
    async def run(self):
        return self._graceful_partial('test')

import asyncio
a = TestAgent('test-id-123', 'secrets', 'test request')
result = asyncio.run(a.run())
print(result)

try:
    asyncio.run(a.run())
    print('ERROR: should have raised')
except Exception as e:
    print(f'double-run blocked: {e}')
"
```
