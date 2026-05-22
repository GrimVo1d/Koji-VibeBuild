"""
Декоратор с экспоненциальной задержкой для transient-ошибок.

Используется в hot-paths, где сеть/Koji могут моргнуть:
- koji CLI subprocess (resolver.KojiClient._run_koji_command)
- HTTP-загрузки SRPM (fetcher)
- submit-команды (builder._run_koji)

ВАЖНО: retry НЕ должен скрывать программные баги — мы повторяем только при
указанных в `transient_marker`-функции исключениях/сигналах.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable)

# Маркеры transient-ошибок (по подстрокам в str(exc) или в stdout/stderr).
_TRANSIENT_MARKERS = (
    "connection",
    "timeout",
    "timed out",
    "temporary failure",
    "temporarily unavailable",
    "service unavailable",
    "gateway",
    "bad gateway",
    "503",
    "502",
    "504",
    "ssl: ",
    "remote end closed",
    "network is unreachable",
    "no route to host",
)


def is_transient(exc_or_text) -> bool:
    """Проверить, выглядит ли ошибка как transient (заслуживает retry)."""
    if exc_or_text is None:
        return False
    text = str(exc_or_text).lower()
    return any(m in text for m in _TRANSIENT_MARKERS)


def with_retry(
    attempts: int = 3,
    backoff: float = 2.0,
    initial_delay: float = 1.0,
    transient_check: Optional[Callable[[BaseException], bool]] = None,
):
    """
    Декоратор: повторяет вызов до `attempts` раз с экспоненциальным backoff.

    Args:
        attempts: общее число попыток (включая первую). 3 = 1 первая + 2 retry.
        backoff: множитель задержки (1.0 → 2.0 → 4.0 …).
        initial_delay: первая задержка в секундах.
        transient_check: предикат, определяющий «transient» исключения.
                          По умолчанию — is_transient.
    """
    if transient_check is None:
        transient_check = lambda exc: is_transient(exc)  # noqa: E731

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exc: Optional[BaseException] = None
            for attempt in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt >= attempts:
                        raise
                    if not transient_check(exc):
                        raise
                    logger.warning(
                        "%s попытка %d/%d упала (%s: %s); жду %.1fs",
                        fn.__name__,
                        attempt,
                        attempts,
                        type(exc).__name__,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
                    delay *= backoff
            # Недостижимо, но для тайпчекера
            assert last_exc is not None
            raise last_exc

        return wrapper  # type: ignore[return-value]

    return decorator
