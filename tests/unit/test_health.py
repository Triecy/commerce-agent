from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from commerce_agent.api.app import REQUEST_ID_HEADER, create_app, tcp_probe
from commerce_agent.common.config import Settings


def _client(**checks: bool | Exception) -> TestClient:
    def make(result: bool | Exception):  # type: ignore[no-untyped-def]
        async def check() -> bool:
            if isinstance(result, Exception):
                raise result
            return result

        return check

    app = create_app(Settings(), readiness_checks={k: make(v) for k, v in checks.items()})
    return TestClient(app)


def test_healthz_ok_without_dependencies() -> None:
    resp = _client(postgres=False, redis=False).get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_ready_when_all_checks_pass() -> None:
    resp = _client(postgres=True, redis=True).get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "checks": {"postgres": True, "redis": True}}


def test_readyz_503_when_a_check_fails() -> None:
    resp = _client(postgres=True, redis=False).get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["checks"] == {"postgres": True, "redis": False}


def test_readyz_treats_check_exception_as_not_ready() -> None:
    resp = _client(postgres=RuntimeError("boom"), redis=True).get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"


def test_request_id_is_echoed_or_generated() -> None:
    client = _client(postgres=True, redis=True)
    assert (
        client.get("/healthz", headers={REQUEST_ID_HEADER: "abc-123"}).headers[REQUEST_ID_HEADER]
        == "abc-123"
    )
    generated = client.get("/healthz", headers={REQUEST_ID_HEADER: "bad id\n"}).headers[
        REQUEST_ID_HEADER
    ]
    assert generated != "bad id\n"
    assert len(generated) == 32


def test_cors_allow_list_is_applied() -> None:
    app = create_app(Settings(cors_allow_origins=["http://ok.test"]), readiness_checks={})
    client = TestClient(app)
    allowed = client.get("/healthz", headers={"Origin": "http://ok.test"})
    denied = client.get("/healthz", headers={"Origin": "http://evil.test"})
    assert allowed.headers.get("access-control-allow-origin") == "http://ok.test"
    assert "access-control-allow-origin" not in denied.headers


def test_tcp_probe_false_for_closed_port() -> None:
    # Port 1 on localhost is essentially never listening; the timeout bounds the wait.
    assert asyncio.run(tcp_probe("127.0.0.1", 1, timeout_s=0.5)) is False


@pytest.mark.parametrize("timeout_s", [0.2])
def test_tcp_probe_true_for_listening_socket(timeout_s: float) -> None:
    async def scenario() -> bool:
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            return await tcp_probe("127.0.0.1", port, timeout_s)

    assert asyncio.run(scenario()) is True
