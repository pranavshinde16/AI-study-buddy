"""structlog setup: JSON log lines (or readable console lines when LOG_JSON=false).

Every log line automatically carries the current request's `request_id` (bound by the
request-id middleware through structlog's contextvars).
"""

import logging
import sys

import structlog


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    renderer = structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )

    # Route uvicorn/sqlalchemy stdlib logs through the same level.
    logging.basicConfig(level=level.upper(), stream=sys.stdout, format="%(message)s")
