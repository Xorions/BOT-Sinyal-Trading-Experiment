"""Tes unit untuk data/history.py: penyimpanan & evaluasi per sesi (PAGI/MALAM)."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import data.history as history
from signals.engine import ACTION_BUY, ACTION_SELL, Signal


def _signal(symbol, coin_id, action=ACTION_BUY, price=100.0, sl=None, tp1=None, tp2=None):
    return Signal(
        coin_id=coin_id,
        symbol=symbol,
        name=symbol,
        price=price,
        price_change_24h=0.0,
        score=4.0,
        action=action,
        confidence=80,
        sl=sl if sl is not None else price * 0.92,
        tp1=tp1 if tp1 is not None else price * 1.05,
        tp2=tp2 if tp2 is not None else price * 1.10,
    )


class SessionTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        history.HISTORY_FILE = os.path.join(self._tmp.name, "history.json")

    def tearDown(self):
        self._tmp.cleanup()


class TestSessions(SessionTestCase):
    def test_append_and_load_by_session(self):
        history.append_signals([_signal("BTC", "bitcoin")], session=history.SESSION_PAGI)
        entry = history.load_last_entry(session=history.SESSION_MALAM)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["session"], history.SESSION_PAGI)
        self.assertEqual(entry["signals"][0]["symbol"], "BTC")

    def test_same_session_overwrites(self):
        history.append_signals([_signal("BTC", "bitcoin", price=100.0)], session=history.SESSION_PAGI)
        history.append_signals([_signal("ETH", "ethereum", price=50.0)], session=history.SESSION_PAGI)
        entries = history.load_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["signals"][0]["symbol"], "ETH")

    def test_malam_evaluates_pagi(self):
        history.append_signals([_signal("BTC", "bitcoin", price=100.0)], session=history.SESSION_PAGI)
        price_map = {
            "bitcoin": {"current_price": 112.0, "high_24h": 115.0, "low_24h": 99.0}
        }
        entry = history.load_last_entry(session=history.SESSION_MALAM)
        evals = history.evaluate_entry(entry, price_map)
        self.assertEqual(evals[0].result, history.RESULT_TP2)

    def test_pagi_evaluates_previous_day_malam(self):
        history.append_signals([_signal("BTC", "bitcoin", price=100.0)], session=history.SESSION_MALAM)
        entry = history.load_last_entry(session=history.SESSION_PAGI)
        self.assertEqual(entry["session"], history.SESSION_MALAM)

    def test_old_entry_without_session_defaults_pagi(self):
        history._save_entries(
            [
                {
                    "date": "2026-08-07",
                    "signals": [
                        {"coin_id": "x", "symbol": "X", "action": "BUY", "entry": 1, "sl": 0.9, "tp1": 1.05, "tp2": 1.1}
                    ],
                }
            ]
        )
        entry = history.load_last_entry(session=history.SESSION_MALAM)
        self.assertEqual(entry.get("session", history.DEFAULT_SESSION), history.DEFAULT_SESSION)


class TestScan24x7History(SessionTestCase):
    """Mode 24/7: satu entri per sinyal + antrian evaluasi ke group publik."""

    def test_append_scan_signal_creates_independent_entry(self):
        history.append_scan_signal(_signal("BTC", "bitcoin", price=100.0))
        history.append_scan_signal(_signal("ETH", "ethereum", price=50.0))
        entries = history.load_entries()
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(e["session"] == history.SESSION_SCAN for e in entries))
        self.assertTrue(all(e["evaluated_at"] is None for e in entries))

    def test_pending_entries_skip_fresh_and_evaluated(self):
        history.append_scan_signal(_signal("BTC", "bitcoin"))
        pending = history.load_pending_entries(min_age_hours=0, max_age_hours=24)
        self.assertEqual(len(pending), 1)
        history.mark_entry_evaluated(pending[0])
        self.assertEqual(history.load_pending_entries(min_age_hours=0, max_age_hours=24), [])

    def test_pending_entries_age_filter(self):
        history.append_scan_signal(_signal("BTC", "bitcoin"))
        self.assertEqual(history.load_pending_entries(min_age_hours=10, max_age_hours=24), [])

    def test_mark_evaluated_only_touches_matching_entry(self):
        history.append_scan_signal(_signal("BTC", "bitcoin"))
        history.append_scan_signal(_signal("ETH", "ethereum"))
        entries = history.load_entries()
        history.mark_entry_evaluated(entries[0])
        remaining = history.load_entries()
        evaluated = [e for e in remaining if e["evaluated_at"]]
        self.assertEqual(len(evaluated), 1)
        self.assertEqual(evaluated[0]["signals"][0]["symbol"], "BTC")

    def test_format_evaluation_pending_mentions_result(self):
        history.append_scan_signal(_signal("BTC", "bitcoin", price=100.0))
        pending = history.load_pending_entries(min_age_hours=0, max_age_hours=24)
        price_map = {
            "bitcoin": {"current_price": 112.0, "high_24h": 115.0, "low_24h": 99.0}
        }
        messages = history.format_evaluation_pending(pending, price_map)
        self.assertEqual(len(messages), 1)
        self.assertIn("HIT TP2", messages[0])
        self.assertIn("#BTC", messages[0])

    def test_session_entries_not_in_pending(self):
        history.append_signals([_signal("BTC", "bitcoin")], session=history.SESSION_PAGI)
        self.assertEqual(history.load_pending_entries(min_age_hours=0, max_age_hours=24), [])

    def test_last_session_entry_skips_scan_entries(self):
        history.append_scan_signal(_signal("BTC", "bitcoin", price=100.0))
        history.append_signals([_signal("ETH", "ethereum")], session=history.SESSION_PAGI)
        entry = history.load_last_session_entry(session=history.SESSION_MALAM)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["session"], history.SESSION_PAGI)
        self.assertEqual(entry["signals"][0]["symbol"], "ETH")

    def test_last_session_entry_none_when_only_scan(self):
        history.append_scan_signal(_signal("BTC", "bitcoin", price=100.0))
        self.assertIsNone(history.load_last_session_entry(session=history.SESSION_MALAM))


_WIB_TZ = timezone(timedelta(hours=7))


def _days_ago_wib(days: int) -> str:
    return (datetime.now(_WIB_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")


class TestRecentSessionEntries(SessionTestCase):
    def _seed(self):
        history._save_entries(
            [
                {  # entri mode SCAN (24/7) → dilewati
                    "date": _days_ago_wib(1),
                    "session": history.SESSION_SCAN,
                    "saved_at": "a",
                    "signals": [{"coin_id": "s", "symbol": "S"}],
                },
                {  # sesi berjalan hari ini → dikecualikan
                    "date": _days_ago_wib(0),
                    "session": history.SESSION_MALAM,
                    "saved_at": "b",
                    "signals": [{"coin_id": "cur", "symbol": "CUR"}],
                },
                {  # terlalu tua → dilewati
                    "date": _days_ago_wib(10),
                    "session": history.SESSION_PAGI,
                    "saved_at": "c",
                    "signals": [{"coin_id": "old", "symbol": "OLD"}],
                },
                {  # segar 2 hari lalu → masuk (paling lama)
                    "date": _days_ago_wib(2),
                    "session": history.SESSION_PAGI,
                    "saved_at": "d",
                    "signals": [{"coin_id": "r1", "symbol": "R1"}],
                },
                {  # segar 1 hari lalu → masuk (terbaru)
                    "date": _days_ago_wib(1),
                    "session": history.SESSION_MALAM,
                    "saved_at": "e",
                    "signals": [{"coin_id": "r2", "symbol": "R2"}],
                },
            ]
        )

    def test_only_recent_pagi_malam_entries_sorted(self):
        self._seed()
        recent = history.load_recent_session_entries()
        self.assertEqual([e["saved_at"] for e in recent], ["d", "e"])

    def test_custom_age_window_excludes_old(self):
        self._seed()
        # Umur dihitung dari tengah malam tanggal entri, jadi entri "1 hari
        # lalu" berumur 24-48 jam: lolos jendela 2 hari, gugur di jendela <2.
        recent = history.load_recent_session_entries(max_age_days=2)
        self.assertEqual([e["saved_at"] for e in recent], ["e"])


if __name__ == "__main__":
    unittest.main()
