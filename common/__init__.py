"""Utilidades compartilhadas entre os microsserviços."""

from .logging_config import configurar_logs, log_evento, middleware_logs

__all__ = ["configurar_logs", "log_evento", "middleware_logs"]
