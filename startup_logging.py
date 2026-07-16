"""Capture console output for GUI launches that have no visible terminal."""

from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import TextIO


_TRANSCRIPT_STATE = None


def build_runtime_log_path(app_dir, app_version, now=None):
    timestamp = now or datetime.now()
    filename = f"runtime-v{app_version}-{timestamp:%Y%m%d}.log"
    return Path(app_dir) / "runtime_logs" / filename


class TeeTextStream:
    def __init__(self, primary: TextIO | None, transcript: TextIO, lock):
        self._primary = primary
        self._transcript = transcript
        self._lock = lock

    @property
    def encoding(self):
        return getattr(self._primary, "encoding", None) or "utf-8"

    @property
    def errors(self):
        return getattr(self._primary, "errors", None) or "strict"

    def isatty(self):
        return bool(self._primary and self._primary.isatty())

    def writable(self):
        return True

    def write(self, text):
        if not isinstance(text, str):
            text = str(text)
        with self._lock:
            if self._primary is not None:
                try:
                    self._primary.write(text)
                    self._primary.flush()
                except (OSError, UnicodeError, ValueError):
                    pass
            self._transcript.write(text)
            self._transcript.flush()
        return len(text)

    def flush(self):
        with self._lock:
            if self._primary is not None:
                try:
                    self._primary.flush()
                except (OSError, UnicodeError, ValueError):
                    pass
            self._transcript.flush()


def configure_console_transcript(app_dir, app_version, app_name=None):
    """Tee stdout/stderr to a versioned UTF-8 file and return its path."""
    global _TRANSCRIPT_STATE
    if _TRANSCRIPT_STATE is not None:
        return _TRANSCRIPT_STATE[0]

    log_path = build_runtime_log_path(app_dir, app_version)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        transcript = log_path.open("a", encoding="utf-8", buffering=1)
    except OSError as exc:
        target = sys.stderr or sys.__stderr__
        if target is not None:
            print(f"[startup] cannot open console transcript: {exc}", file=target)
        return None

    lock = threading.RLock()
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    sys.stdout = TeeTextStream(original_stdout, transcript, lock)
    sys.stderr = TeeTextStream(original_stderr, transcript, lock)

    def log_unhandled_exception(exc_type, exc_value, exc_traceback):
        print("[unhandled exception]", file=sys.stderr)
        traceback.print_exception(
            exc_type, exc_value, exc_traceback, file=sys.stderr
        )

    sys.excepthook = log_unhandled_exception
    _TRANSCRIPT_STATE = (log_path, transcript, original_stdout, original_stderr)

    print("")
    if app_name:
        print(f"[startup] app name: {app_name}")
    print(f"[startup] app version: {app_version}")
    print(f"[startup] time: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"[startup] console transcript: {log_path}")
    return log_path
