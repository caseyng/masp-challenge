/skill:python-engineering

## Task: Implement SecretsSubAgent

Read `SPEC.md` (§5 Component Contracts — SecretsSubAgent, §7, §16 Extension
Contracts, §19 Security Properties) and `CLAUDE.md` before writing.

### File to create

**`/root/challenge/agents/secrets.py`**

### Existing files to read first

- `agents/base.py` — BaseSubAgent, lifecycle, `_graceful_partial`
- `models.py` — SubAgentResult, ToolOutput
- `exceptions.py` — ToolError, LLMError
- `tools.py` — `scan_filesystem_for_secrets(path: str) -> list[dict]`
- `llm_client.py` — LLMClient

### What SecretsSubAgent does

Scans the filesystem for secret-looking patterns, then asks the LLM to reason
about the findings and assign a severity. Returns a `SubAgentResult`.

### `run()` implementation steps

1. Call `scan_filesystem_for_secrets(path=".")` using `asyncio.to_thread()`.
   - On `ToolError`: record a failed ToolOutput, set `tool_status = "error"`.
   - On success: record a successful ToolOutput with summary of match count.

2. Build LLM context from tool results:
   - MUST NOT include matched secret values — only file paths, line numbers, pattern categories.
   - If tool failed: mention that the scan failed.
   - Keep it concise: list up to 20 matches; if more, summarise count by category.

3. Call `LLMClient().call(system=SYSTEM_PROMPT, user=user_msg)`.
   - On `LLMError`: set `status = "partial"`, derive findings from raw tool output, skip LLM reasoning.
   - On success: parse findings and severity from LLM response.

4. Return `SubAgentResult`.

### System prompt (define as module-level constant)

```python
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
```

### Parsing LLM response

Extract severity from the last line matching `SEVERITY: <label>`. If no such line
exists, default to `"Medium"`. Extract findings as the non-empty lines before the
SEVERITY line.

### Fallback when LLM fails (status = "partial")

Derive findings from raw tool output: one finding per unique pattern_category found,
e.g. `"Found 3 matches for pattern: api_key_assignment in 2 files"`. Severity = `"Medium"`.

### ToolOutput to record

```python
ToolOutput(
    tool_name="scan_filesystem_for_secrets",
    status="ok" | "error",
    summary=f"Found {n} pattern matches across {m} files" | error message,
)
```

### Imports

```python
import asyncio
from agents.base import BaseSubAgent
from models import SubAgentResult, ToolOutput
from exceptions import ToolError, LLMError
from tools import scan_filesystem_for_secrets
from llm_client import LLMClient
```

### Verify

```bash
cd /root/challenge && python -c "
from agents.secrets import SecretsSubAgent
import asyncio
a = SecretsSubAgent('id-001', 'secrets', 'test audit request')
result = asyncio.run(a.run())
print(result)
assert result.agent_type == 'secrets'
assert result.status in ('complete', 'partial', 'failed')
assert result.severity in ('Critical','High','Medium','Low','Info')
print('ok')
"
```
