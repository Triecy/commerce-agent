"""FastAPI gateway. P0 exposes only liveness and readiness probes."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from commerce_agent.common.config import Settings, get_settings
from commerce_agent.common.logging import configure_logging, log_context, trace_id_from_traceparent

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

ReadinessCheck = Callable[[], Awaitable[bool]]


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, bool]


async def tcp_probe(host: str, port: int, timeout_s: float) -> bool:
    """True if a TCP connection opens within ``timeout_s`` (timeout is enforced)."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout_s)
    except (TimeoutError, OSError):
        return False
    writer.close()
    with contextlib.suppress(TimeoutError, OSError):
        await asyncio.wait_for(writer.wait_closed(), timeout_s)
    return True


def default_readiness_checks(settings: Settings) -> dict[str, ReadinessCheck]:
    timeout = settings.readiness_timeout_s

    async def postgres() -> bool:
        return await tcp_probe(settings.postgres_host, settings.postgres_port, timeout)

    async def redis() -> bool:
        return await tcp_probe(settings.redis_host, settings.redis_port, timeout)

    return {"postgres": postgres, "redis": redis}


def create_app(
    settings: Settings | None = None,
    readiness_checks: dict[str, ReadinessCheck] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)
    checks = (
        readiness_checks if readiness_checks is not None else default_readiness_checks(settings)
    )

    app = FastAPI(title="Commerce Agent", version="0.0.1")
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming and _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        trace_id = trace_id_from_traceparent(request.headers.get("traceparent"))
        with log_context(request_id, trace_id):
            response = await call_next(request)
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                },
            )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        """Liveness: the process is up. Never touches dependencies."""
        return HealthResponse(status="ok")

    @app.get("/readyz", response_model=ReadinessResponse)
    async def readyz(response: Response) -> ReadinessResponse:
        """Readiness: every dependency probe passes; otherwise 503."""
        names = list(checks)
        results = await asyncio.gather(*(checks[name]() for name in names), return_exceptions=True)
        status = {name: result is True for name, result in zip(names, results, strict=True)}
        ready = all(status.values())
        if not ready:
            response.status_code = 503
        return ReadinessResponse(status="ready" if ready else "not_ready", checks=status)

    return app
