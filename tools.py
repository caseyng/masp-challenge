from __future__ import annotations

import configparser
import json
import os
import re
import socket

from exceptions import ToolError

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

SERVICE_HINTS = {
    22: "SSH", 80: "HTTP", 443: "HTTPS", 3000: "Node/React dev",
    3306: "MySQL", 5432: "PostgreSQL", 5672: "RabbitMQ", 6379: "Redis",
    8080: "HTTP alt", 8443: "HTTPS alt", 8888: "Jupyter", 27017: "MongoDB",
}

SENSITIVE_PATTERNS = [
    "KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "PWD",
    "CREDENTIAL", "AUTH", "PRIVATE", "API",
]

CONFIG_EXTENSIONS = {".yaml", ".yml", ".json", ".ini", ".env", ".cfg"}


def scan_filesystem_for_secrets(path: str) -> list[dict]:
    results = []
    visited_inodes: set[int] = set()

    try:
        for root, dirs, files in os.walk(path, followlinks=False):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    stat = os.lstat(fpath)
                    inode = stat.st_ino
                    if inode in visited_inodes:
                        continue
                    visited_inodes.add(inode)

                    if os.path.islink(fpath):
                        real = os.path.realpath(fpath)
                        real_stat = os.stat(real)
                        if real_stat.st_ino in visited_inodes:
                            continue
                        visited_inodes.add(real_stat.st_ino)
                        fpath = real

                    if stat.st_size > 1_000_000:
                        continue

                    try:
                        with open(fpath, "rb") as f:
                            header = f.read(512)
                            if b"\x00" in header:
                                continue
                    except (PermissionError, OSError):
                        continue

                    try:
                        with open(fpath, encoding="utf-8", errors="replace") as f:
                            for lineno, line in enumerate(f, 1):
                                for cat, pat in PATTERNS.items():
                                    if pat.search(line):
                                        results.append({
                                            "file": fpath,
                                            "line_number": lineno,
                                            "pattern_category": cat,
                                        })
                    except (PermissionError, OSError):
                        continue
                except (PermissionError, OSError):
                    continue
    except OSError as exc:
        raise ToolError(f"Filesystem scan failed: {exc}") from exc

    return results


def probe_local_ports(ports: list[int]) -> list[dict]:
    if not ports:
        return []
    results = []
    for port in ports:
        service_hint = SERVICE_HINTS.get(port, "unknown")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                status = "open"
        except ConnectionRefusedError:
            status = "closed"
        except OSError:
            status = "error"
        results.append({"port": port, "status": status, "service_hint": service_hint})
    return results


def inspect_environment_variables() -> list[dict]:
    results = []
    for name in os.environ:
        upper = name.upper()
        for pat in SENSITIVE_PATTERNS:
            if pat in upper:
                results.append({"name": name, "sensitivity_hint": f"contains {pat}"})
                break
    return results


def scan_config_files(path: str) -> list[dict]:
    results = []

    def _walk(base: str, depth: int) -> None:
        if depth > 5:
            return
        try:
            entries = os.scandir(base)
        except OSError:
            return
        with entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    _walk(entry.path, depth + 1)
                elif entry.is_file(follow_symlinks=False):
                    _, ext = os.path.splitext(entry.name)
                    if ext.lower() not in CONFIG_EXTENSIONS:
                        continue
                    try:
                        if entry.stat().st_size > 500_000:
                            continue
                    except OSError:
                        continue
                    _scan_file(entry.path, ext.lower())

    def _scan_file(fpath: str, ext: str) -> None:
        if ext in (".yaml", ".yml"):
            try:
                import yaml
                with open(fpath, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict):
                    _check_dict(fpath, data)
            except Exception:
                return
        elif ext == ".json":
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    _check_dict(fpath, data)
            except Exception:
                return
        elif ext == ".env":
            try:
                with open(fpath, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key = line.split("=", 1)[0].strip()
                            key_upper = key.upper()
                            for pat in SENSITIVE_PATTERNS:
                                if pat in key_upper:
                                    results.append({
                                        "file": fpath,
                                        "issue": "sensitive value in env file",
                                        "key": key,
                                    })
                                    break
            except Exception:
                return
        elif ext in (".ini", ".cfg"):
            try:
                cp = configparser.ConfigParser()
                cp.read(fpath, encoding="utf-8")
                for section in cp.sections():
                    for key in cp.options(section):
                        if "password" in key.lower() or "secret" in key.lower():
                            results.append({
                                "file": fpath,
                                "issue": "credential key in config",
                                "key": key,
                            })
            except Exception:
                return

    def _check_dict(fpath: str, data: dict, prefix: str = "") -> None:
        for k, v in data.items():
            key_lower = k.lower()
            if key_lower == "debug" and v:
                results.append({"file": fpath, "issue": "debug mode enabled", "key": k})
            elif key_lower in ("password", "passwd") and v:
                results.append({"file": fpath, "issue": "plaintext credential key present", "key": k})
            elif key_lower == "host" and v == "0.0.0.0":
                results.append({"file": fpath, "issue": "binds all interfaces", "key": k})
            elif key_lower in ("ssl", "tls", "verify_ssl", "verify_tls") and not v:
                results.append({"file": fpath, "issue": "TLS verification disabled", "key": k})
            if isinstance(v, dict):
                _check_dict(fpath, v)

    _walk(path, 0)
    return results
