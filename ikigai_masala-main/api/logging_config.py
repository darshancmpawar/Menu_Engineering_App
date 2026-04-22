"""
Structured logging and request tracing for the Flask API.

Two things live here:

1. ``configure_logging()`` — one-shot dictConfig that installs either a
   human-readable formatter (default, same shape as the old basicConfig
   line) or a JSON formatter when ``LOG_FORMAT=json``. The JSON output
   is minimal on purpose — no extra dependency, just enough fields for
   log aggregators (Datadog, Loki, CloudWatch) to index and query.

2. ``request_id_var`` + ``RequestIdFilter`` — a ContextVar plus a
   logging filter that stamps every record with the active request's
   id. Callers don't have to remember to pass it; any ``logger.info(...)``
   inside a handler automatically carries the right id.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import logging.config
import os
import uuid
from contextvars import ContextVar
from typing import Optional

# The current request's id. Outside a request context this stays "-".
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    """Return a short random id for a new request."""
    return uuid.uuid4().hex[:12]


class RequestIdFilter(logging.Filter):
    """Stamp every log record with the current request_id ContextVar."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter — no dependency, stable schema.

    Keeps the record compact: {ts, level, logger, msg, request_id,
    plus any ``extra=`` fields the caller passed}. Exceptions are
    serialised as a single ``exc`` string; log aggregators can split
    multiline stack traces server-side.
    """

    _RESERVED = frozenset({
        'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
        'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
        'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
        'thread', 'threadName', 'processName', 'process', 'message',
        'asctime', 'taskName',
    })

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": dt.datetime.fromtimestamp(
                record.created, tz=dt.timezone.utc,
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Any caller-supplied `extra=` keys land directly on the record.
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            if key in payload:
                continue
            if key == "request_id":
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(
    log_format: Optional[str] = None,
    level: str = "INFO",
) -> None:
    """Install the root logging handler. Idempotent — safe to call from
    multiple entry points (``api.app`` import, Streamlit bootstrap).

    Args:
        log_format: ``"json"`` for structured output, anything else for
            the human format. Defaults to ``LOG_FORMAT`` env var.
        level: root log level. Defaults to ``LOG_LEVEL`` env var or INFO.
    """
    log_format = (log_format or os.getenv("LOG_FORMAT", "")).strip().lower()
    level = (os.getenv("LOG_LEVEL") or level).upper()

    if log_format == "json":
        formatter = {"()": JsonFormatter}
    else:
        formatter = {
            "format": "%(asctime)s [%(levelname)s] "
                      "%(name)s [%(request_id)s]: %(message)s",
        }

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": RequestIdFilter},
        },
        "formatters": {"app": formatter},
        "handlers": {
            "stderr": {
                "class": "logging.StreamHandler",
                "formatter": "app",
                "filters": ["request_id"],
            },
        },
        "root": {
            "level": level,
            "handlers": ["stderr"],
        },
        # Quiet Werkzeug's per-request noise — Flask's access-log line
        # is handled by our after_request hook with richer fields.
        "loggers": {
            "werkzeug": {"level": "WARNING"},
        },
    })
