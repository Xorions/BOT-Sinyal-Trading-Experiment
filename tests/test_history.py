"""Tes unit untuk data/history.py: penyimpanan & evaluasi per sesi (PAGI/MALAM)."""

import json
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


# "Now" tetap untuk tes yang bergantung waktu — deterministik lintas tengah malam.
_FIXED_NOW = datetime(2026, 8, 24, 12, 0, tzinfo=_WIB_TZ)


def _iso_hours_before_now(hours: float) -> str:
    return (_FIXED_NOW - timedelta(hours=hours)).isoformat(timespec="seconds")


class TestRecentSessionEntries(SessionTestCase):
    def _seed(self):
        history._save_entries(
            [
                {  # entri mode SCAN (24/7) → dilewati
                    "date": "2026-08-23",
                    "session": history.SESSION_SCAN,
                    "saved_at": "a",
                    "signals": [{"coin_id": "s", "symbol": "S"}],
                },
                {  # sesi berjalan (hari ini, PAGI @ now 12:00 WIB) → dikecualikan
                    "date": "2026-08-24",
                    "session": history.SESSION_PAGI,
                    "saved_at": "b",
                    "signals": [{"coin_id": "cur", "symbol": "CUR"}],
                },
                {  # terlalu tua → dilewati
                    "date": "2026-08-14",
                    "session": history.SESSION_PAGI,
                    "saved_at": "c",
                    "signals": [{"coin_id": "old", "symbol": "OLD"}],
                },
                {  # segar 2 hari lalu → masuk (paling lama)
                    "date": "2026-08-22",
                    "session": history.SESSION_PAGI,
                    "saved_at": "d",
                    "signals": [{"coin_id": "r1", "symbol": "R1"}],
                },
                {  # segar 1 hari lalu → masuk (terbaru)
                    "date": "2026-08-23",
                    "session": history.SESSION_MALAM,
                    "saved_at": "e",
                    "signals": [{"coin_id": "r2", "symbol": "R2"}],
                },
            ]
        )

    def test_only_recent_pagi_malam_entries_sorted(self):
        self._seed()
        recent = history.load_recent_session_entries(now=_FIXED_NOW)
        self.assertEqual([e["saved_at"] for e in recent], ["d", "e"])

    def test_custom_age_window_excludes_old(self):
        self._seed()
        recent = history.load_recent_session_entries(max_age_days=2, now=_FIXED_NOW)
        self.assertEqual([e["saved_at"] for e in recent], ["e"])


def _record(symbol, coin_id, action=ACTION_BUY, entry=100.0, sl=90.0, tp1=120.0, tp2=130.0, result=None):
    record = {
        "coin_id": coin_id,
        "symbol": symbol,
        "name": symbol,
        "action": action,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }
    if result:
        record["result"] = result
    return record


class TestResultsTracking(SessionTestCase):
    def _scan_entry(self, saved_iso):
        return {
            "date": saved_iso[:10],
            "session": history.SESSION_SCAN,
            "key": f"test:{saved_iso}",
            "saved_at": saved_iso,
            "evaluated_at": None,
            "signals": [_record("BTC", "bitcoin")],
        }

    _PM_TP2 = {"bitcoin": {"current_price": 131.0, "high_24h": 132.0, "low_24h": 95.0}}
    _PM_MID = {"bitcoin": {"current_price": 105.0, "high_24h": 106.0, "low_24h": 99.0}}
    _PM_SL = {"bitcoin": {"current_price": 88.0, "high_24h": 92.0, "low_24h": 87.0}}

    def test_results_locked_never_downgraded(self):
        history._save_entries([self._scan_entry(_iso_hours_before_now(5))])
        self.assertTrue(history.update_results(self._PM_TP2, now=_FIXED_NOW))
        with open(history.HISTORY_FILE, encoding="utf-8") as fh:
            stored = json.load(fh)
        signal = stored["entries"][0]["signals"][0]
        self.assertEqual(signal["result"], history.RESULT_TP2)
        self.assertEqual(signal["result_price"], 131.0)
        # Cek berikutnya harga jatuh ke bawah SL → hasil TP2 TIDAK boleh turun.
        self.assertFalse(history.update_results(self._PM_SL, now=_FIXED_NOW))
        self.assertEqual(history.load_entries()[0]["signals"][0]["result"], history.RESULT_TP2)

    def test_floating_upgrades_later(self):
        history._save_entries([self._scan_entry(_iso_hours_before_now(5))])
        self.assertTrue(history.update_results(self._PM_MID, now=_FIXED_NOW))
        self.assertEqual(history.load_entries()[0]["signals"][0]["result"], history.RESULT_FLOATING)
        self.assertTrue(history.update_results(self._PM_TP2, now=_FIXED_NOW))
        self.assertEqual(history.load_entries()[0]["signals"][0]["result"], history.RESULT_TP2)

    def test_entries_beyond_lookback_skipped(self):
        history._save_entries([self._scan_entry(_iso_hours_before_now(100.0))])
        self.assertFalse(history.update_results(self._PM_SL, now=_FIXED_NOW))
        self.assertIsNone(history.load_entries()[0]["signals"][0].get("result"))


class TestWinrate(SessionTestCase):
    def _seed(self):
        history._save_entries(
            [
                {
                    "date": "2026-08-20",
                    "session": history.SESSION_SCAN,
                    "saved_at": "x1",
                    "signals": [
                        _record("TP2", "tp2", result=history.RESULT_TP2),
                        _record("SL", "sl", result=history.RESULT_SL),
                        _record("FLOAT", "float"),
                    ],
                },
                {
                    "date": "2026-08-21",
                    "session": history.SESSION_SCAN,
                    "saved_at": "x2",
                    "signals": [
                        _record(
                            "SELLTP1",
                            "selltp1",
                            action=ACTION_SELL,
                            entry=100.0,
                            sl=110.0,
                            tp1=80.0,
                            tp2=70.0,
                            result=history.RESULT_TP1,
                        )
                    ],
                },
                {
                    "date": "2026-08-01",
                    "session": history.SESSION_PAGI,
                    "saved_at": "x3",
                    "signals": [_record("OLD", "old", result=history.RESULT_TP2)],  # luar jendela 7 hari
                },
            ]
        )

    def test_winrate_stats_math_and_window(self):
        self._seed()
        stats = history.winrate_stats(now=_FIXED_NOW)
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["closed"], 3)
        self.assertEqual(stats["floating"], 1)
        self.assertEqual(stats["tp2"], 1)
        self.assertEqual(stats["tp1"], 1)
        self.assertEqual(stats["sl"], 1)
        self.assertAlmostEqual(stats["win_rate"], 2 / 3 * 100.0)
        # TP2 BUY: 0.5*(2R)+0.5*(3R)=2.5 · SL: -1.0 · TP1 SELL: +2.0 → rata-rata 1.1667
        self.assertAlmostEqual(stats["expectancy"], (2.5 - 1.0 + 2.0) / 3.0)

    def test_format_winrate_summary_contains_numbers(self):
        self._seed()
        text = history.format_winrate_summary(now=_FIXED_NOW)
        self.assertIn("PERFORMA SINYAL 7 HARI TERAKHIR", text)
        self.assertIn("Win rate: 67%", text)
        self.assertIn("Ekspektasi: +1.17R/trade", text)

    def test_format_winrate_summary_empty(self):
        text = history.format_winrate_summary(entries=[])
        self.assertIn("Belum ada sinyal", text)


class TestWinrateDigest(SessionTestCase):
    def test_digest_once_per_day_after_min_hour(self):
        self.assertFalse(history.should_send_winrate_digest(now=_FIXED_NOW.replace(hour=6)))
        self.assertTrue(history.should_send_winrate_digest(now=_FIXED_NOW))
        history.mark_winrate_digest_sent(_FIXED_NOW)
        self.assertFalse(history.should_send_winrate_digest(now=_FIXED_NOW))
        # Keesokan harinya kirim lagi.
        tomorrow = _FIXED_NOW + timedelta(days=1)
        self.assertTrue(history.should_send_winrate_digest(now=tomorrow))


class TestDailyEvaluation(SessionTestCase):
    def _seed_day(self, date_str, results):
        """Buat entri SCAN dengan 1 sinyal per hasil tertentu.

        Setiap tuple: (symbol, coin_id, action, entry, sl, tp1, tp2).
        """
        for symbol, coin_id, action, entry, sl, tp1, tp2 in results:
            history.append_scan_signal(
                Signal(
                    coin_id=coin_id,
                    symbol=symbol,
                    name=symbol,
                    price=entry,
                    price_change_24h=0.0,
                    score=4.0,
                    action=action,
                    confidence=80,
                    sl=sl,
                    tp1=tp1,
                    tp2=tp2,
                )
            )
            # Timpa tanggal entri terbaru agar sesuai date_str.
            entries = history.load_entries()
            entries[-1]["date"] = date_str
            history._save_entries(entries)

    def test_format_daily_evaluation_contains_breakdown(self):
        self._seed_day(
            "2026-08-16",
            [
                ("BTC", "bitcoin", ACTION_BUY, 100.0, 95.0, 105.0, 110.0),
                ("ETH", "ethereum", ACTION_BUY, 50.0, 52.0, 48.0, 46.0),
            ],
        )
        entries = history.load_entries_by_date("2026-08-16")
        price_map = {
            "bitcoin": {"current_price": 110.0, "high_24h": 111.0, "low_24h": 99.0},
            "ethereum": {"current_price": 48.0, "high_24h": 51.0, "low_24h": 47.0},
        }
        text = history.format_daily_evaluation(entries, price_map, "2026-08-16")
        self.assertIn("EVALUASI SINYAL HARI SEBELUMNYA", text)
        self.assertIn("Terdapat (2 Coin)", text)
        self.assertIn("HIT TP2: 2", text)
        self.assertIn("#BTC (BUY) →", text)

    def test_daily_eval_once_per_day_after_min_hour(self):
        now = _FIXED_NOW.replace(hour=6)
        self.assertFalse(history.should_send_daily_evaluation(now=now))
        self.assertTrue(history.should_send_daily_evaluation(now=_FIXED_NOW))
        history.mark_daily_evaluation_sent(_FIXED_NOW)
        self.assertFalse(history.should_send_daily_evaluation(now=_FIXED_NOW))
        tomorrow = _FIXED_NOW + timedelta(days=1)
        self.assertTrue(history.should_send_daily_evaluation(now=tomorrow))


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
