"""Barreras de seguridad de la API de AutoBrillo AI.

No sustituye la autenticación del proveedor. Su objetivo es aplicar controles
mínimos en servidor: rate limiting, comparación constante y redacción de
secretos antes de devolver errores o escribir diagnósticos.
"""
from __future__ import annotations

import hmac
import re
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int = 30, window_seconds: int = 60):
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            cutoff = now - self.window_seconds
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def cleanup(self) -> None:
        now = time.monotonic()
        with self._lock:
            cutoff = now - self.window_seconds
            stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
            for key in stale:
                self._hits.pop(key, None)


def constant_time_equal(provided: str | None, expected: str) -> bool:
    return bool(provided) and bool(expected) and hmac.compare_digest(provided, expected)


_SECRET_PATTERNS = (
    r"(?i)(authorization|client[_-]?secret|secret[_-]?key|access[_-]?token|refresh[_-]?token|code[_-]?verifier|password|api[_-]?key)\s*[:=]\s*[^,;\s}]+",
    r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+",
    r"(?i)(APP(?:_USR)?|TG)-[A-Za-z0-9._-]+",
)


def redact(value: object, max_length: int = 1000) -> str:
    text = str(value)[:max_length]
    for pattern in _SECRET_PATTERNS:
        text = re.sub(pattern, "[redacted]", text)
    return text.strip()
