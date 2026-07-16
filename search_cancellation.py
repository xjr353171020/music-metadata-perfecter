"""Shared cooperative-cancellation helpers for network searches."""

from __future__ import annotations


class SearchCancelled(BaseException):
    """Raised at a safe checkpoint after a search cancellation request."""


def is_cancelled(cancel_event) -> bool:
    return bool(cancel_event is not None and cancel_event.is_set())


def check_cancelled(cancel_event) -> None:
    if is_cancelled(cancel_event):
        raise SearchCancelled()


def cancellable_wait(cancel_event, seconds: float) -> None:
    if cancel_event is not None:
        if cancel_event.wait(seconds):
            raise SearchCancelled()
    else:
        import time
        time.sleep(seconds)
