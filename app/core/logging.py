import logging
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON with standard structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        """Return the log record serialised as a JSON string."""
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "service": "repogator",
            "logger": record.name,
        }

        # Attach correlation_id if it was injected via LoggerAdapter extra
        if hasattr(record, "correlation_id"):
            log_entry["correlation_id"] = record.correlation_id

        # Attach any extra fields the caller passed
        for key, value in record.__dict__.items():
            if key not in (
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "id",
                "levelname",
                "levelno",
                "lineno",
                "message",
                "module",
                "msecs",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
                "correlation_id",
                "service",
                "logger",
            ):
                try:
                    json.dumps(value)
                    log_entry[key] = value
                except (TypeError, ValueError):
                    log_entry[key] = str(value)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def get_logger(name: str) -> logging.Logger:
    """Return a logger configured with JSON structured output.

    Args:
        name: The logger name, typically __name__ of the calling module.

    Returns:
        A standard library Logger instance that emits JSON to stdout.
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.propagate = False

    logger.setLevel(logging.DEBUG)
    return logger


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that injects a correlation ID into every request.

    Reads X-Correlation-ID from the incoming request headers. If the header is
    absent a new UUID4 is generated. The value is stored on request.state and
    echoed back in the response headers.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        """Process request, injecting correlation_id into request.state."""
        correlation_id = request.headers.get("X-Correlation-ID") or str(
            uuid.uuid4()
        )
        request.state.correlation_id = correlation_id

        response: Response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
