"""
JSON-форматтер логов для production-парсинга (rsyslog/loki/elastic).

Использование:
    setup_logging(verbose=True, json_logs=True)

Любой `logger.info("msg", extra={"package": "X"})` будет сериализован как JSON
с timestamp/level/module/message/package полями.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

# Атрибуты LogRecord, которые мы НЕ копируем в JSON (всё, что есть в стандарте).
_STANDARD_ATTRS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName",
        "taskName",  # Python 3.12+
    }
)


class JsonFormatter(logging.Formatter):
    """Форматтер, кодирующий LogRecord как JSON-объект на строке."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
        }
        # Кастомные поля из logger.info(..., extra={...})
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)
