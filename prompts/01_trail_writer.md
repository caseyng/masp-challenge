/skill:python-engineering

## Task: Implement AuditTrailWriter

Read `SPEC.md` (§5 Component Contracts — AuditTrailWriter, §10 Atomicity, §18
Observability Contract) and `CLAUDE.md` before writing.

### File to create

**`/root/challenge/trail_writer.py`**

### What this component does (from SPEC.md §5)

`AuditTrailWriter` is a stateful component that owns an open file handle to
`audit_trail.jsonl`. The Orchestrator calls it; sub-agents never call it directly.

### Lifecycle (SPEC.md §6)

```
CLOSED → open(path) → OPEN → close() → CLOSED
```

- `open()` in OPEN state raises `OrchestratorError`
- `close()` is idempotent — calling it in CLOSED state is a no-op
- `append()` in CLOSED state raises `OrchestratorError`

### Contract

```python
class AuditTrailWriter:
    def open(self, path: str) -> None: ...
    def append(self, entry: AuditTrailEntry) -> None: ...
    def close(self) -> None: ...
```

### Behaviour requirements

- `open()`: creates or truncates the file at `path`, opens for append in UTF-8.
  Raises `OrchestratorError` wrapping the OS error if the file cannot be opened.
- `append(entry)`: serialises `entry` using `to_jsonl_line()` from `models.py`,
  writes it followed by `\n`, then calls `flush()` on the file handle.
  If the write or flush raises, re-raise as `OrchestratorError`.
- `close()`: flushes and closes the file handle. Idempotent.

### Atomicity (SPEC.md §10)

Each `append()` flushes one entry. A process kill between two appends leaves all
prior entries intact. The in-progress entry may be truncated — that is acceptable.

### Serialisation

Import `to_jsonl_line` from `models`. Do NOT implement JSON serialisation here.

### Imports available

```python
from models import AuditTrailEntry, to_jsonl_line
from exceptions import OrchestratorError
```

### __repr__

`AuditTrailWriter(path='...', state='OPEN'|'CLOSED')`

### Verify

After writing, run:
```bash
cd /root/challenge && python -c "
from trail_writer import AuditTrailWriter
from models import AuditTrailEntry
import tempfile, os
with tempfile.NamedTemporaryFile(delete=False, suffix='.jsonl') as f:
    path = f.name
w = AuditTrailWriter()
w.open(path)
w.append(AuditTrailEntry(ts='2026-01-01T00:00:00.000Z', event_type='run_start', agent_id=None, agent_type=None, payload={'request': 'test'}))
w.close()
w.close()  # idempotent
print(open(path, encoding='utf-8').read())
os.unlink(path)
"
```
Expected: one valid JSON line printed, no errors on second `close()`.
