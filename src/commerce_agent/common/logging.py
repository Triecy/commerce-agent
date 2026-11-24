"""Structured logging with request-scoped ``request_id`` and ``trace_id`` fields (FR-B3).

Context is carried in :mod:`contextvars`, so it is correct across asyncio tasks.
``trace_id`` is taken from a W3C ``traceparent`` header for now; OpenTelemetry
replaces that source in P7 without changing the log format.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

_RESERVED = frozenset(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class ContextFilter(logging.Filter):
    """Copy the current request context onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.trace_id = trace_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line; extra ``logger.info(..., extra={...})`` keys are kept."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "trace_id": getattr(record, "trace_id", None),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_CONSOLE_FORMAT = (
    "%(asctime)s %(levelname)-8s %(name)s [req=%(request_id)s trace=%(trace_id)s] %(message)s"
)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Install a single stdout handler on the root logger (idempotent)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter() if fmt == "json" else logging.Formatter(_CONSOLE_FORMAT))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


@contextmanager
def log_context(request_id: str | None, trace_id: str | None = None) -> Iterator[None]:
    """Bind ``request_id`` / ``trace_id`` for the duration of the block."""
    req_token = request_id_var.set(request_id)
    trace_token = trace_id_var.set(trace_id)
    try:
        yield
    finally:
        trace_id_var.reset(trace_token)
        request_id_var.reset(req_token)


def trace_id_from_traceparent(header: str | None) -> str | None:
    """Extract the trace id from a W3C ``traceparent`` header, or ``None`` if invalid."""
    if not header:
        return None
    parts = header.strip().split("-")
    if len(parts) != 4 or len(parts[1]) != 32:
        return None
    trace_id = parts[1].lower()
    if trace_id == "0" * 32 or any(c not in "0123456789abcdef" for c in trace_id):
        return None
    return trace_id
