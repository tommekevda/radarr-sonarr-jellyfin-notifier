import logging
import os


class HealthLogFilter(logging.Filter):
    """Filter out health endpoint hits from werkzeug logs."""

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        args = getattr(record, "args", ())
        # record.args[0] holds the request line, e.g. "GET /health HTTP/1.1"
        return not (args and "/health" in str(args[0]))


def configure_logging() -> None:
    level = _get_log_level()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("werkzeug").addFilter(HealthLogFilter())


def _get_log_level() -> int:
    raw = os.getenv("JELLYFIN_NOTIFIER_LOG_LEVEL", "INFO").strip()
    if not raw:
        return logging.INFO
    if raw.isdigit():
        return int(raw)
    return getattr(logging, raw.upper(), logging.INFO)
