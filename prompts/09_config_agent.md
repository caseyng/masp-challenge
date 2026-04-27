/skill:python-engineering

## Task: Implement ConfigSubAgent

Read `SPEC.md` (§5 Component Contracts — ConfigSubAgent, §19) and `CLAUDE.md`
before writing.

### File to create

**`/root/challenge/agents/config.py`**

### Existing files to read first

- `agents/base.py` — BaseSubAgent, `_graceful_partial`
- `models.py` — SubAgentResult, ToolOutput
- `exceptions.py` — ToolError, LLMError
- `tools.py` — `scan_config_files(path: str) -> list[dict]`
- `llm_client.py` — LLMClient

### `run()` implementation steps

1. Call `scan_config_files(path=".")` using `asyncio.to_thread()`.
   - On `ToolError`: record a failed ToolOutput, continue with empty results.
   - On success: record ToolOutput with count of issues found.

2. Build LLM context: list flagged config issues (file, key, issue description).
   CRITICAL: MUST NOT include config values. Keys and issue descriptions only.

3. Call `LLMClient().call(system=SYSTEM_PROMPT, user=user_msg)`.
   - On `LLMError`: `status = "partial"`, findings from raw results.
   - On success: parse findings and severity.

4. Return `SubAgentResult`.

### System prompt

```python
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
```

### Parsing

Same pattern: extract `SEVERITY:` line, default `"Medium"`.

### Fallback when LLM fails

Findings = one entry per issue: `"{file}: {key} — {issue}"`. Severity = `"Medium"`.

### ToolOutput

```python
ToolOutput(
    tool_name="scan_config_files",
    status="ok" | "error",
    summary=f"{n} configuration issues found across {m} files" | error message,
)
```

### Imports

```python
import asyncio
from agents.base import BaseSubAgent
from models import SubAgentResult, ToolOutput
from exceptions import ToolError, LLMError
from tools import scan_config_files
from llm_client import LLMClient
```

### Verify

```bash
cd /root/challenge && python -c "
from agents.config import ConfigSubAgent
import asyncio
a = ConfigSubAgent('id-004', 'config', 'test audit request')
result = asyncio.run(a.run())
print(result)
assert result.agent_type == 'config'
print('ok')
"
```
