"""Logging JSON estruturado para os serviços HTTP."""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Callable

from starlette.requests import Request

_LOGGER = logging.getLogger("projeto_distribuido")


def configurar_logs() -> logging.Logger:
    """Configura uma saída JSON por linha no stdout, sem duplicar handlers."""
    if not _LOGGER.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False
    return _LOGGER


def log_evento(evento: str, **campos) -> None:
    registro = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "evento": evento,
        **campos,
    }
    configurar_logs().info(json.dumps(registro, ensure_ascii=False, default=str))


async def middleware_logs(request, call_next, *, servico: str,
                          resolver_usuario: Callable[[Request], str | None] | None = None):
    inicio = time.perf_counter()
    usuario = resolver_usuario(request) if resolver_usuario else None
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        log_evento(
            "http_request",
            servico=servico,
            metodo=request.method,
            rota=request.url.path,
            status=status,
            duracao_ms=round((time.perf_counter() - inicio) * 1000, 2),
            usuario=usuario,
        )
