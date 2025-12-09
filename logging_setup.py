import logging


class HealthLogFilter(logging.Filter):
    """Filter out health endpoint hits from werkzeug logs."""

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        args = getattr(record, "args", ())
        # record.args[0] holds the request line, e.g. "GET /health HTTP/1.1"
        return not (args and "/health" in str(args[0]))


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("werkzeug").addFilter(HealthLogFilter())
