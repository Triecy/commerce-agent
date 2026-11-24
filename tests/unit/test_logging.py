from __future__ import annotations

import json
import logging

import pytest

from commerce_agent.common.logging import (
    ContextFilter,
    JsonFormatter,
    log_context,
    request_id_var,
    trace_id_from_traceparent,
)


def _render(msg: str, **extra: object) -> dict[str, object]:
    record = logging.makeLogRecord({"name": "t", "levelname": "INFO", "msg": msg, **extra})
    ContextFilter().filter(record)
    return json.loads(JsonFormatter().format(record))  # type: ignore[no-any-return]


def test_json_line_contains_context_fields() -> None:
    with log_context("req-1", "a" * 32):
        out = _render("hello", user="u1")
    assert out["msg"] == "hello"
    assert out["request_id"] == "req-1"
    assert out["trace_id"] == "a" * 32
    assert out["user"] == "u1"


def test_context_is_reset_after_block() -> None:
    with log_context("req-2"):
        assert request_id_var.get() == "req-2"
    assert request_id_var.get() is None
    assert _render("x")["request_id"] is None


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            "4bf92f3577b34da6a3ce929d0e0e4736",
        ),
        ("00-" + "0" * 32 + "-00f067aa0ba902b7-01", None),
        ("garbage", None),
        ("00-xyz-00f067aa0ba902b7-01", None),
        (None, None),
    ],
)
def test_trace_id_from_traceparent(header: str | None, expected: str | None) -> None:
    assert trace_id_from_traceparent(header) == expected
