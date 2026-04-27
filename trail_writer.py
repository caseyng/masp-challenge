from __future__ import annotations

from models import AuditTrailEntry, to_jsonl_line
from exceptions import OrchestratorError


class AuditTrailWriter:
    def __init__(self) -> None:
        self._file = None
        self._path: str | None = None

    def open(self, path: str) -> None:
        if self._file is not None:
            raise OrchestratorError("AuditTrailWriter already open")
        try:
            self._file = open(path, "w", encoding="utf-8")
            self._path = path
        except OSError as exc:
            raise OrchestratorError(f"Cannot open audit trail: {exc}") from exc

    def append(self, entry: AuditTrailEntry) -> None:
        if self._file is None:
            raise OrchestratorError("AuditTrailWriter is not open")
        try:
            self._file.write(to_jsonl_line(entry) + "\n")
            self._file.flush()
        except OSError as exc:
            raise OrchestratorError(f"Audit trail write failed: {exc}") from exc

    def close(self) -> None:
        if self._file is None:
            return
        try:
            self._file.flush()
            self._file.close()
        finally:
            self._file = None

    def __repr__(self) -> str:
        state = "OPEN" if self._file is not None else "CLOSED"
        return f"AuditTrailWriter(path={self._path!r}, state={state!r})"
