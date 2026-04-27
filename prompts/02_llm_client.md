/skill:python-engineering

## Task: Implement LLMClient

Read `SPEC.md` (§5 Component Contracts — LLM Client, §14 External Dependencies,
§15 Configuration, §7 failure modes `LLM_CALL_FAILURE` and `MISSING_API_KEY`)
and `CLAUDE.md` before writing.

### File to create

**`/root/challenge/llm_client.py`**

### What this component does

`LLMClient` is a stateless wrapper around the LLM provider SDK. It issues a
single chat completion call given a system prompt and a user message, and returns
the text response. It is re-entrant — concurrent calls from multiple sub-agents
are permitted.

### Provider selection (SPEC.md §15)

- If `ANTHROPIC_API_KEY` is set: use Anthropic SDK. `OPENAI_API_KEY` is ignored.
- If only `OPENAI_API_KEY` is set: use OpenAI SDK.
- If neither is set: raise `LLMError("MISSING_API_KEY")` on construction.

### Configuration from environment (SPEC.md §15)

| Env var | Default (Anthropic) | Default (OpenAI) | Notes |
|---|---|---|---|
| `MASP_MODEL` | `claude-sonnet-4-6` | `gpt-4o` | model name passed to SDK |
| `MASP_MAX_TOKENS` | `1024` | `1024` | max tokens in response |
| `MASP_TIMEOUT_SECS` | `30` | `30` | per-call timeout in seconds |

Read these once at construction time.

### Contract

```python
class LLMClient:
    def __init__(self) -> None: ...        # reads env vars, selects provider
    def call(self, system: str, user: str) -> str: ...
```

`call(system, user) -> str`:
- Makes one API call with the given system and user messages.
- Applies a timeout of `MASP_TIMEOUT_SECS` seconds.
- On timeout or rate-limit (HTTP 429): retries **once** after a 1-second sleep.
- On second failure, or any other error: raises `LLMError` with a description.
- Returns the text content of the first choice/message.
- Is stateless — no conversation history, no state between calls.

### Anthropic SDK usage

```python
import anthropic
client = anthropic.Anthropic(api_key=..., timeout=self._timeout)
response = client.messages.create(
    model=self._model,
    max_tokens=self._max_tokens,
    system=system,
    messages=[{"role": "user", "content": user}],
)
return response.content[0].text
```

Catch `anthropic.APITimeoutError`, `anthropic.RateLimitError` for the retry path.
Catch `anthropic.APIError` for the general failure path.

### OpenAI SDK usage

```python
import openai
client = openai.OpenAI(api_key=..., timeout=self._timeout)
response = client.chat.completions.create(
    model=self._model,
    max_tokens=self._max_tokens,
    messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ],
)
return response.choices[0].message.content
```

Catch `openai.APITimeoutError`, `openai.RateLimitError` for retry.
Catch `openai.APIError` for general failure.

### Imports available

```python
from exceptions import LLMError
```

### __repr__

`LLMClient(provider='anthropic'|'openai', model='...')`

### Constraints

- MUST NOT store the API key as an instance attribute after constructing the SDK client.
- MUST NOT log or print the API key anywhere.
- The SDK client object MAY be created once at `__init__` time and reused.
- Both `anthropic` and `openai` packages must appear in `requirements.txt`.

### Verify

After writing, run:
```bash
cd /root/challenge && python -c "from llm_client import LLMClient; print('import ok')"
```
(Full API call test is only possible with a live key — import check is sufficient here.)
