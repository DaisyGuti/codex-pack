import pytest
from billing import retry


def test_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(retry.time, "sleep", lambda _s: None)
    calls = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError
        return "ok"

    assert retry.retry_with_backoff(flaky) == "ok"
    assert len(calls) == 3


def test_gives_up_after_the_last_attempt(monkeypatch):
    monkeypatch.setattr(retry.time, "sleep", lambda _s: None)

    def always() -> str:
        raise ConnectionError

    with pytest.raises(ConnectionError):
        retry.retry_with_backoff(always, attempts=2)
