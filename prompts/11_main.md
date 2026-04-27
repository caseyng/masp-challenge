/skill:python-engineering

## Task: Implement main.py and requirements.txt

Read `SPEC.md` (§3 System Boundary, §15 Configuration) and `CLAUDE.md`
before writing.

### Files to create

**`/root/challenge/main.py`**  
**`/root/challenge/requirements.txt`**

---

### main.py

Entry point. One command: `python main.py "<audit request>"`.

```python
#!/usr/bin/env python3
import sys
import asyncio
from orchestrator import Orchestrator
from exceptions import OrchestratorError
```

`main()` function:

1. Read `sys.argv[1]` as `audit_request`. If absent: print usage to stderr, exit 1.
   ```
   Usage: python main.py "<audit request>"
   Example: python main.py "audit this project for secrets and open ports"
   ```

2. Construct `Orchestrator()`.

3. Call `asyncio.run(orchestrator.run(audit_request))`.

4. On `OrchestratorError`: print the error message to stderr, exit 1.

5. On success: print `"Audit complete. See report.md and audit_trail.jsonl."` to stdout, exit 0.

```python
if __name__ == "__main__":
    main()
```

No argument parsing library needed — `sys.argv` is sufficient for one positional argument.

---

### requirements.txt

Include exactly these packages (no phantom packages):

```
anthropic>=0.40.0
openai>=1.50.0
pyyaml>=6.0
```

**Do not add** any packages not used in the implementation. Verify each package is
used in the codebase before adding it.

---

### End-to-end verify

After writing both files, run:
```bash
cd /root/challenge && pip install -r requirements.txt -q && python main.py 2>&1 | head -3
```
Expected: usage message printed, process exits 1 (no crash, no traceback).

Then if an API key is available:
```bash
cd /root/challenge && python main.py "audit this project for secrets and open ports"
```
Expected: both `report.md` and `audit_trail.jsonl` created in under 60 seconds.
