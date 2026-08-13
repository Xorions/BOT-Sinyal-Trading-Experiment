"""Tes unit untuk notifikasi admin eksekusi di telegram_sender.py (mock, tanpa network)."""

import unittest
from unittest import mock

from telegram_sender import (
    TelegramSendError,
    notify_execution_failed,
    notify_order_executed,
)

REPORT = {
    "symbol": "BTC",
    "action": "BUY",
    "side": "buy",
    "entry": 100.0,
    "sl": 95.0,
    "tp1": 105.0,
    "tp2": 110.0,
    "free_balance": 1000.0,
    "risk_usd": 10.0,
    "amount_coins": 2.0,
    "amount_contracts": 2.0,
    "tp1_amount_contracts": 1.0,
    "tp2_amount_contracts": 1.0,
    "sl_price": "95.00",
    "tp1_price": "105.00",
    "tp2_price": "110.00",
    "order_id": "order-1",
    "tp1_order_id": "order-2",
    "tp2_order_id": "order-3",
}


class TestAdminNotifications(unittest.TestCase):
    def setUp(self):
        self._admin_patch = mock.patch("telegram_sender.TELEGRAM_ADMIN_CHAT_ID", "123456")
        self._admin_patch.start()
        self._send_patch = mock.patch("telegram_sender.send_telegram")
        self.fake_send = self._send_patch.start()

    def tearDown(self):
        self._send_patch.stop()
        self._admin_patch.stop()

    def test_order_executed_sent_to_admin_chat(self):
        notify_order_executed(REPORT)
        self.fake_send.assert_called_once()
        text = self.fake_send.call_args.args[0]
        self.assertEqual(self.fake_send.call_args.kwargs["chat_id"], "123456")
        self.assertIn("🚀", text)
        self.assertIn("[ORDER EXECUTED]", text)
        self.assertIn("#BTC", text)
        self.assertIn("TP1 (50%)", text)
        self.assertIn("TP2 (50%)", text)
        self.assertIn("order-1", text)

    def test_execution_failed_sent_to_admin_chat(self):
        notify_execution_failed("BTC", "Saldo free USDT = 0", "BUY")
        text = self.fake_send.call_args.args[0]
        self.assertIn("⚠️", text)
        self.assertIn("[EXECUTION FAILED]", text)
        self.assertIn("#BTC", text)
        self.assertIn("Saldo free USDT = 0", text)

    def test_missing_admin_chat_id_raises(self):
        with mock.patch("telegram_sender.TELEGRAM_ADMIN_CHAT_ID", ""):
            with self.assertRaises(TelegramSendError):
                notify_order_executed(REPORT)
            with self.assertRaises(TelegramSendError):
                notify_execution_failed("BTC", "gagal")
        self.fake_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
