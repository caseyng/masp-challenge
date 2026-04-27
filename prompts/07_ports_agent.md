/skill:python-engineering

## Task: Implement PortsSubAgent

Read `SPEC.md` (§5 Component Contracts — PortsSubAgent, §7, §16) and `CLAUDE.md`
before writing.

### File to create

**`/root/challenge/agents/ports.py`**

### Existing files to read first

- `agents/base.py` — BaseSubAgent, `_graceful_partial`
- `models.py` — SubAgentResult, ToolOutput
- `exceptions.py` — ToolError, LLMError
- `tools.py` — `probe_local_ports(ports: list[int]) -> list[dict]`
- `llm_client.py` — LLMClient

### Port list to probe (from SPEC.md §5)

```python
PORTS_TO_PROBE = [22, 80, 443, 3000, 3306, 5432, 5672, 6379, 8080, 8443, 8888, 27017]
```

Define this as a module-level constant.

### `run()` implementation steps

1. Call `probe_local_ports(PORTS_TO_PROBE)` using `asyncio.to_thread()`.
   - On `ToolError`: record a failed ToolOutput, continue with empty results.
   - On success: record a successful ToolOutput with count of open ports.

2. Build LLM context: list only the **open** ports and their service hints.
   If no ports are open, say so. Keep to one paragraph.

3. Call `LLMClient().call(system=SYSTEM_PROMPT, user=user_msg)`.
   - On `LLMError`: `status = "partial"`, findings derived from raw results.
   - On success: parse findings and severity.

4. Return `SubAgentResult`.

### System prompt

```python
SYSTEM_PROMPT = """You are a security analyst reviewing open network ports on a local system.

You will receive a list of open TCP ports and their likely services.

Your task:
1. Assess the security risk: Critical, High, Medium, Low, or Info.
   - Critical: database ports (3306, 5432, 27017) exposed on localhost without expected service
   - High: remote access (22), message brokers (5672, 6379) open unexpectedly
   - Medium: web servers (80, 8080, 3000) or dev tools (8888) open
   - Low: HTTPS (443, 8443) open — expected but worth noting
   - Info: no open ports found
2. List findings as bullet points naming the port, service, and risk.
3. End with: SEVERITY: <label>

Be concise."""
```

### Parsing

Same as SecretsSubAgent: extract `SEVERITY:` from last matching line, default `"Low"`.

### Fallback when LLM fails

Findings = one entry per open port: `"Port {port} ({service_hint}) is open"`.
Severity = `"Low"`.

### ToolOutput

```python
ToolOutput(
    tool_name="probe_local_ports",
    status="ok" | "error",
    summary=f"{n} open ports found: {open_port_list}" | error message,
)
```

### Imports

```python
import asyncio
from agents.base import BaseSubAgent
from models import SubAgentResult, ToolOutput
from exceptions import ToolError, LLMError
from tools import probe_local_ports
from llm_client import LLMClient
```

### Verify

```bash
cd /root/challenge && python -c "
from agents.ports import PortsSubAgent
import asyncio
a = PortsSubAgent('id-002', 'ports', 'test audit request')
result = asyncio.run(a.run())
print(result)
assert result.agent_type == 'ports'
assert result.status in ('complete', 'partial', 'failed')
print('ok')
"
```
