/skill:python-engineering

## Task: Implement EnvSubAgent

Read `SPEC.md` (§5 Component Contracts — EnvSubAgent, §19 Security Properties) and
`CLAUDE.md` before writing.

### File to create

**`/root/challenge/agents/env.py`**

### Existing files to read first

- `agents/base.py` — BaseSubAgent, `_graceful_partial`
- `models.py` — SubAgentResult, ToolOutput
- `exceptions.py` — ToolError, LLMError
- `tools.py` — `inspect_environment_variables() -> list[dict]`
- `llm_client.py` — LLMClient

### `run()` implementation steps

1. Call `inspect_environment_variables()` using `asyncio.to_thread()`.
   - On `ToolError`: record a failed ToolOutput, continue with empty results.
   - On success: record a successful ToolOutput with count of flagged names.

2. Build LLM context: list flagged env var **names** and their sensitivity hints.
   CRITICAL: MUST NOT include env var values. Names only.

3. Call `LLMClient().call(system=SYSTEM_PROMPT, user=user_msg)`.
   - On `LLMError`: `status = "partial"`, findings from raw results.
   - On success: parse findings and severity.

4. Return `SubAgentResult`.

### System prompt

```python
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
```

### Parsing

Same pattern: extract `SEVERITY:` line, default `"Low"`.

### Fallback when LLM fails

Findings = one entry per flagged name: `"Sensitive env var name present: {name}"`.
Severity = `"Medium"`.

### ToolOutput

```python
ToolOutput(
    tool_name="inspect_environment_variables",
    status="ok" | "error",
    summary=f"{n} sensitive env var names found" | error message,
)
```

### Imports

```python
import asyncio
from agents.base import BaseSubAgent
from models import SubAgentResult, ToolOutput
from exceptions import ToolError, LLMError
from tools import inspect_environment_variables
from llm_client import LLMClient
```

### Verify

```bash
cd /root/challenge && python -c "
from agents.env import EnvSubAgent
import asyncio
a = EnvSubAgent('id-003', 'env', 'test audit request')
result = asyncio.run(a.run())
print(result)
assert result.agent_type == 'env'
print('ok')
"
```
