"""Tes unit untuk data/cooldown.py: cooldown anti-spam sinyal (mode 24/7)."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import data.cooldown as cooldown


class CooldownTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        cooldown.COOLDOWN_FILE = os.path.join(self._tmp.name, "cooldown.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_not_blocked_when_empty(self):
        self.assertFalse(cooldown.is_blocked("BTC", "BUY", 6.0))

    def test_record_then_blocked(self):
        cooldown.record_sent("BTC", "BUY")
        self.assertTrue(cooldown.is_blocked("BTC", "BUY", 6.0))

    def test_other_direction_not_blocked(self):
        cooldown.record_sent("BTC", "BUY")
        self.assertFalse(cooldown.is_blocked("BTC", "SELL", 6.0))

    def test_cooldown_expires(self):
        cooldown.record_sent("ETH", "BUY")
        old = datetime.now(timezone.utc) - timedelta(hours=7)
        data = cooldown._load()
        data["ETH:BUY"] = old.isoformat(timespec="seconds")
        cooldown._save(data)
        self.assertFalse(cooldown.is_blocked("ETH", "BUY", 6.0))

    def test_cooldown_zero_disables(self):
        cooldown.record_sent("BTC", "BUY")
        self.assertFalse(cooldown.is_blocked("BTC", "BUY", 0.0))

    def test_key_normalized(self):
        self.assertEqual(cooldown.cooldown_key("btc", "buy"), "BTC:BUY")


if __name__ == "__main__":
    unittest.main()