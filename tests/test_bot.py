"""Tes unit untuk bot.py: pemilihan evaluasi legacy & skip bila semua tuntas."""

import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone

import bot
from data.history import Eval


_WIB_TZ = timezone(timedelta(hours=7))


def _eval(symbol, result):
    return Eval(
        symbol=symbol,
        action="BUY",
        entry=100.0,
        sl=90.0,
        tp1=120.0,
        tp2=130.0,
        result=result,
        price=100.0,
    )


class TestEvaluatePreviousSession(unittest.TestCase):
    """Evaluasi legacy memakai entri terbaru yang masih punya sinyal FLOATING."""

    def _run_eval(self, entries_asc, evals_per_entry_newest_first):
        """entries_asc urut lama->terbaru; evals dievaluasi dari yang terbaru.

        Referensi mock disimpan sendiri karena mock.patch.multiple tidak
        mengembalikan mock yang dilewatkan eksplisit dalam dict hasilnya.
        """
        mocks = {
            "coin_price_map": mock.Mock(return_value={}),
            "get_prices_for_ids": mock.Mock(return_value={}),
            "load_recent_session_entries": mock.Mock(return_value=list(entries_asc)),
            "evaluate_entry": mock.Mock(side_effect=evals_per_entry_newest_first),
            "format_evaluation": mock.Mock(return_value="EVAL"),
        }
        with mock.patch.multiple(bot, **mocks):
            message = bot.evaluate_previous_session([])
        return message, mocks

    def test_shows_newest_entry_with_floating_signal(self):
        older = {"date": "2026-08-23", "signals": [{"coin_id": "a"}]}
        newer = {"date": "2026-08-24", "signals": [{"coin_id": "b"}]}
        # Evaluasi dimulai dari entri TERBARU; yang ini masih ada FLOATING.
        evals_newer = [_eval("B", "HIT TP1"), _eval("C", "FLOATING")]
        evals_older = [_eval("A", "HIT TP2")]
        message, mocks = self._run_eval(
            [older, newer], [evals_newer, evals_older]
        )
        self.assertEqual(message, "EVAL")
        mocks["format_evaluation"].assert_called_once_with(newer, {})
        # Entri lebih lama tidak sempat dicek karena terbaru sudah lolos.
        self.assertEqual(mocks["evaluate_entry"].call_count, 1)

    def test_empty_when_all_final(self):
        entries = [
            {"date": "2026-08-16", "signals": [{"coin_id": "a"}, {"coin_id": "b"}]}
        ]
        evals = [_eval("CASHCAT", "HIT TP2"), _eval("GENIUS", "HIT SL")]
        message, _ = self._run_eval(entries, [evals])
        self.assertEqual(message, "")

    def test_falls_back_to_older_when_newest_all_final(self):
        older = {"date": "2026-08-22", "signals": [{"coin_id": "a"}]}
        newer = {"date": "2026-08-24", "signals": [{"coin_id": "b"}]}
        evals_newer = [_eval("B", "HIT SL")]
        evals_older = [_eval("A", "FLOATING")]
        message, mocks = self._run_eval([older, newer], [evals_newer, evals_older])
        self.assertEqual(message, "EVAL")
        mocks["format_evaluation"].assert_called_once_with(older, {})


class TestSendPreviousSessionEvaluation(unittest.TestCase):
    def test_skips_sending_when_nothing_pending(self):
        mocks = {
            "TELEGRAM_BOT_TOKEN": "token",
            "eval_chat_id": mock.Mock(return_value="123"),
            "evaluate_previous_session": mock.Mock(return_value="  "),
            "generate_chart_url": mock.Mock(),
            "send_telegram": mock.Mock(),
        }
        with mock.patch.multiple(bot, **mocks):
            bot.send_previous_session_evaluation([])
        mocks["send_telegram"].assert_not_called()
        mocks["generate_chart_url"].assert_not_called()

    def test_sends_with_chart_when_pending(self):
        entry = {"date": "2026-08-24", "signals": [{"symbol": "BTC", "action": "BUY"}]}
        mocks = {
            "TELEGRAM_BOT_TOKEN": "token",
            "eval_chat_id": mock.Mock(return_value="123"),
            "evaluate_previous_session": mock.Mock(return_value="<b>EVAL</b>"),
            "load_recent_session_entries": mock.Mock(return_value=[entry]),
            "generate_chart_url": mock.Mock(return_value="https://chart/x.png"),
            "send_telegram": mock.Mock(),
        }
        with mock.patch.multiple(bot, **mocks):
            bot.send_previous_session_evaluation([])
        mocks["send_telegram"].assert_called_once()
        kwargs = mocks["send_telegram"].call_args.kwargs
        self.assertEqual(kwargs["chat_id"], "123")
        self.assertEqual(kwargs["image_url"], "https://chart/x.png")


if __name__ == "__main__":
    unittest.main()
