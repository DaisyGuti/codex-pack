"""Retry a flaky call with a growing pause between attempts."""

import time
from collections.abc import Callable


def retry_with_backoff[T](
    func: Callable[[], T],
    attempts: int = 5,
    retry_on: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError),
) -> T:
    delay = 0.5
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except retry_on:
            if attempt == attempts:
                raise
            time.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")


def charge_with_retry(charge: Callable[[], str]) -> str:
    return retry_with_backoff(charge)
