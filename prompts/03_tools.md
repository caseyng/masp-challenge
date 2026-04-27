/skill:python-engineering

## Task: Implement the four tool functions

Read `SPEC.md` (§5 Component Contracts per specialist sub-agent, §8 Boundary
Conditions, §12 Interaction Contracts — Sub-Agent → Tool, §19 Security Properties)
and `CLAUDE.md` before writing.

### File to create

**`/root/challenge/tools.py`**

### What tools are

Tools are stateless, side-effect-free functions. They perform real local operations
(filesystem, network, env) and return structured results. They MUST NOT:
- Modify any file, process, or network state.
- Call LLMs.
- Hold open handles on return.
- Take longer than 10 seconds (raise `ToolError("timeout")` if they would).

All four functions raise `ToolError` on failure. Never raise any other exception type.

---

### Tool 1: `scan_filesystem_for_secrets`

```python
def scan_filesystem_for_secrets(path: str) -> list[dict]:
```

Recursively walks `path`. For each **text** file (skip binary files, skip files
>1MB), scans lines against the patterns below. Returns a list of match dicts.

**Returns** (list of dicts, one per match found):
```python
{"file": str, "line_number": int, "pattern_category": str}
```

**CRITICAL — SPEC.md §19:** The matched secret string MUST NOT appear in the
return value. Only `file`, `line_number`, and `pattern_category` are returned.

**Patterns to detect** (compile once at module level):
```python
PATTERNS = {
    "private_key_header": re.compile(
        r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
    ),
    "api_key_assignment": re.compile(
        r"(?i)(api[_\-]?key|apikey)\s*[=:]\s*\S{8,}"
    ),
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "generic_secret": re.compile(
        r"(?i)(secret|token|password|passwd|pwd)\s*[=:]\s*\S{8,}"
    ),
    "anthropic_openai_key": re.compile(r"sk-[a-zA-Z0-9\-_]{20,}"),
}
```

**Boundary conditions (SPEC.md §8):**
- Empty directory: return `[]`, no error.
- File with no read permission: skip it; do not raise.
- Symlink: follow at most once (track visited inodes).
- Binary file: skip (check for null bytes in first 512 bytes).

---

### Tool 2: `probe_local_ports`

```python
def probe_local_ports(ports: list[int]) -> list[dict]:
```

For each port in `ports`, attempts a TCP connect to `127.0.0.1`. Timeout per
probe: 2 seconds. Returns results for all ports.

**Returns** (list of dicts, one per port):
```python
{"port": int, "status": "open" | "closed" | "error", "service_hint": str}
```

`service_hint`: a human-readable guess at the service (e.g. `"SSH"`, `"HTTP"`,
`"PostgreSQL"`). Use a static lookup table keyed by port number; return `"unknown"`
if the port is not in the table.

**Static service hints table** (define at module level):
```python
SERVICE_HINTS = {
    22: "SSH", 80: "HTTP", 443: "HTTPS", 3000: "Node/React dev",
    3306: "MySQL", 5432: "PostgreSQL", 5672: "RabbitMQ", 6379: "Redis",
    8080: "HTTP alt", 8443: "HTTPS alt", 8888: "Jupyter", 27017: "MongoDB",
}
```

`status`:
- `"open"`: TCP connection succeeded (connection refused = `"closed"`)
- `"closed"`: connection refused
- `"error"`: timeout or other socket error

**Boundary (SPEC.md §8):**
- Empty `ports` list: return `[]`.
- Port that times out: `status: "error"`.

---

### Tool 3: `inspect_environment_variables`

```python
def inspect_environment_variables() -> list[dict]:
```

Scans `os.environ` for variable names that match sensitivity patterns.
Returns a list of flagged variable names.

**CRITICAL — SPEC.md §19:** Values MUST NOT appear in the return value.
Only names are returned.

**Returns** (list of dicts):
```python
{"name": str, "sensitivity_hint": str}
```

`sensitivity_hint`: why this name was flagged (e.g. `"contains KEY"`,
`"contains SECRET"`, `"contains TOKEN"`).

**Sensitivity patterns** (check var NAME, not value):
```python
SENSITIVE_PATTERNS = [
    "KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "PWD",
    "CREDENTIAL", "AUTH", "PRIVATE", "API",
]
```
Flag if the uppercased name contains any of these as a substring.

**Boundary:** Empty environment: return `[]`.

---

### Tool 4: `scan_config_files`

```python
def scan_config_files(path: str) -> list[dict]:
```

Finds all `.yaml`, `.yml`, `.json`, `.ini`, `.env`, `.cfg` files recursively
under `path` (max depth 5). For each file, attempts to parse it and look for
insecure configuration patterns.

**Returns** (list of dicts):
```python
{"file": str, "issue": str, "key": str}
```

**CRITICAL — SPEC.md §19:** Values MUST NOT appear in the return value.
Only key names and issue descriptions are returned.

**Patterns to detect:**

For YAML/JSON:
- Key `debug` with truthy value → issue `"debug mode enabled"`
- Key `password` or `passwd` with non-empty value → issue `"plaintext credential key present"`
- Key `host` with value `"0.0.0.0"` → issue `"binds all interfaces"`
- Key `ssl` or `tls` or `verify_ssl` or `verify_tls` with falsy value → issue `"TLS verification disabled"`

For .env files (key=value pairs):
- Key matches `SENSITIVE_PATTERNS` from above → issue `"sensitive value in env file"`

For .ini/.cfg:
- Any key containing `password` or `secret` → issue `"credential key in config"`

**Boundary:**
- File parse error: skip the file; do not raise.
- Empty directory: return `[]`.
- File >500KB: skip.

---

### Module-level structure

Define patterns and lookup tables as module-level constants (not inside functions).
Functions are stateless — no class needed, no instance state.

### Imports available

```python
from exceptions import ToolError
import os, re, socket, json, struct
```

For YAML parsing, use `import yaml` (PyYAML). For .ini, use `import configparser`.

### Verify

After writing, run:
```bash
cd /root/challenge && python -c "
from tools import scan_filesystem_for_secrets, probe_local_ports, inspect_environment_variables, scan_config_files
print('scan_secrets:', scan_filesystem_for_secrets('.'))
print('probe_ports:', probe_local_ports([22, 80, 8080]))
print('inspect_env:', inspect_environment_variables()[:3])
print('scan_config:', scan_config_files('.'))
print('all ok')
"
```
Expected: no exceptions, lists returned (may be empty).
