"""OpenTelemetry tracing + structured logging for the Objectivism Library TUI.

Provides the Telemetry class as a lightweight facade over OTel's TracerProvider
and a trace-aware logging adapter. All span creation is exception-safe so
instrumentation cannot crash the app.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Generator

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


class _Span:
    """Thin span wrapper that swallows OTel exceptions to keep the app running."""

    def __init__(self, span: object) -> None:
        self._span = span

    def set_attribute(self, key: str, value: object) -> None:
        """Set a span attribute, ignoring any OTel errors."""
        try:
            self._span.set_attribute(key, value)  # type: ignore[attr-defined]
        except Exception:
            pass

    def record_exception(self, exc: BaseException) -> None:
        """Record an exception on the span, ignoring any OTel errors."""
        try:
            self._span.record_exception(exc)  # type: ignore[attr-defined]
        except Exception:
            pass


class _OtelLogAdapter(logging.LoggerAdapter):
    """LoggerAdapter that injects trace_id and span_id into every log record."""

    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:  # type: ignore[override]
        span = trace.get_current_span()
        ctx = span.get_span_context()
        extra = kwargs.get("extra", {})
        if ctx.is_valid:
            extra["trace_id"] = format(ctx.trace_id, "032x")
            extra["span_id"] = format(ctx.span_id, "016x")
        kwargs["extra"] = extra
        return msg, kwargs


class Telemetry:
    """Thin OTel facade for TUI observability.

    Provides a span() context manager for creating OTel spans and a
    trace-aware logger. All operations are exception-safe — instrumentation
    cannot crash the application.
    """

    def __init__(self, tracer: object) -> None:
        self._tracer = tracer
        self.log: _OtelLogAdapter = _OtelLogAdapter(
            logging.getLogger("objlib.tui"), {}
        )

    @contextmanager
    def span(self, name: str) -> Generator[_Span, None, None]:
        """Create an OTel span as a context manager.

        Args:
            name: Span name (e.g., ``"tui.search"``).

        Yields:
            _Span wrapper for setting attributes and recording exceptions.
        """
        with self._tracer.start_as_current_span(name) as otel_span:  # type: ignore[attr-defined]
            yield _Span(otel_span)

    @classmethod
    def for_testing(cls) -> tuple["Telemetry", InMemorySpanExporter]:
        """Create a Telemetry instance with an in-memory exporter for tests.

        Returns:
            ``(Telemetry, InMemorySpanExporter)`` — call
            ``exporter.get_finished_spans()`` after test execution to assert
            span names and attributes.
        """
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("objlib.tui")
        return cls(tracer), exporter

    @classmethod
    def noop(cls) -> "Telemetry":
        """Create a no-op Telemetry instance (spans are discarded).

        Use when no tracing backend is configured. All methods are safe to call.
        """
        provider = TracerProvider()  # No processors — spans discarded silently
        return cls(provider.get_tracer("objlib.tui"))


# ---------------------------------------------------------------------------
# Module-level singleton — lets widgets call get_telemetry() without
# holding a reference to the App. ObjlibApp.__init__ calls set_telemetry()
# so the singleton is always up-to-date before any widget code runs.
# ---------------------------------------------------------------------------

_singleton: Telemetry | None = None


def get_telemetry() -> Telemetry:
    """Return the active Telemetry instance (noop if not yet configured)."""
    global _singleton
    if _singleton is None:
        _singleton = Telemetry.noop()
    return _singleton


def set_telemetry(tel: Telemetry) -> None:
    """Replace the active Telemetry instance (called by ObjlibApp.__init__)."""
    global _singleton
    _singleton = tel


# ---------------------------------------------------------------------------
# File logging helpers
# ---------------------------------------------------------------------------


class _DefaultsFilter(logging.Filter):
    """Ensure trace_id and span_id are always present on log records.

    Provides zero-value defaults when a log is emitted outside any active span
    so the JSON formatter can always emit ``trace`` and ``span`` fields.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id"):
            record.trace_id = "0" * 32  # type: ignore[attr-defined]
        if not hasattr(record, "span_id"):
            record.span_id = "0" * 16  # type: ignore[attr-defined]
        return True


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line for machine-readable log files.

    Each line is independently ``json.loads``-able with keys:
    ``ts``, ``level``, ``logger``, ``trace``, ``span``, ``msg``.
    """

    def format(self, record: logging.LogRecord) -> str:
        # Ensure defaults exist (belt-and-suspenders alongside _DefaultsFilter)
        trace_id = getattr(record, "trace_id", "0" * 32)
        span_id = getattr(record, "span_id", "0" * 16)
        return json.dumps(
            {
                "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "trace": trace_id,
                "span": span_id,
                "msg": record.getMessage(),
            },
            ensure_ascii=False,
        )


def configure_file_logging(log_dir: str = "logs") -> None:
    """Configure the objlib.tui logger to write JSON-lines logs to a file.

    Creates ``{log_dir}/tui-YYYYMMDD.log`` with one JSON object per line.
    Each line has keys: ``ts``, ``level``, ``logger``, ``trace``, ``span``, ``msg``.

    Call once from ``run_tui()``; tests do not call this so they stay clean.

    Args:
        log_dir: Directory to write log files into (created if absent).
    """
    import os
    from datetime import datetime

    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(
        log_dir, f"tui-{datetime.now().strftime('%Y%m%d')}.log"
    )

    logger = logging.getLogger("objlib.tui")

    # Guard: skip if a FileHandler already exists for this logger.
    # Prevents duplicate entries if configure_file_logging() is ever called twice.
    if any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        return

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.addFilter(_DefaultsFilter())
    handler.setFormatter(_JsonFormatter())

    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
