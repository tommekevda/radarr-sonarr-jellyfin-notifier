import logging
import unittest

from radarr_sonarr_jellyfin_notifier.logging_setup import HealthLogFilter


class LoggingSetupTests(unittest.TestCase):
    def test_health_log_filter_blocks_health(self):
        filt = HealthLogFilter()
        record = logging.LogRecord("werkzeug", logging.INFO, "", 0, "", (), None)
        record.args = ("GET /health HTTP/1.1",)
        self.assertFalse(filt.filter(record))

    def test_health_log_filter_allows_other_paths(self):
        filt = HealthLogFilter()
        record = logging.LogRecord("werkzeug", logging.INFO, "", 0, "", (), None)
        record.args = ("GET /radarr-webhook HTTP/1.1",)
        self.assertTrue(filt.filter(record))

    def test_health_log_filter_allows_empty_args(self):
        filt = HealthLogFilter()
        record = logging.LogRecord("werkzeug", logging.INFO, "", 0, "", (), None)
        record.args = ()
        self.assertTrue(filt.filter(record))


if __name__ == "__main__":
    unittest.main()
