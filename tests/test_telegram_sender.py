"""Tes unit untuk notifikasi admin eksekusi di telegram_sender.py (mock, tanpa network)."""

import unittest
from unittest import mock

from telegram_sender import (
    PHOTO_CAPTION_MAX,
    TelegramSendError,
    notify_execution_failed,
    notify_order_executed,
    send_telegram,
    send_telegram_photo,
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


class TestPhotoNotifications(unittest.TestCase):
    """Pengiriman foto chart (sendPhoto) beserta fallback ke sendMessage."""

    IMAGE_URL = "https://r2.chart-img.com/tradingview/advanced-chart/snapshot/abc.png"

    def setUp(self):
        self._token = mock.patch("telegram_sender.TELEGRAM_BOT_TOKEN", "token")
        self._chat = mock.patch("telegram_sender.TELEGRAM_CHAT_ID", "123456")
        self._token.start()
        self._chat.start()

    def tearDown(self):
        self._chat.stop()
        self._token.stop()

    def _mock_post(self, status=200):
        resp = mock.Mock()
        resp.status_code = status
        resp.text = "error"
        return resp

    def test_image_url_uses_sendphoto_with_caption(self):
        with mock.patch("telegram_sender.requests.post") as post:
            post.return_value = self._mock_post()
            send_telegram("<b>Sinyal BTC</b>", image_url=self.IMAGE_URL)

        self.assertEqual(post.call_count, 1)
        url = post.call_args.args[0]
        self.assertIn("/sendPhoto", url)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["chat_id"], "123456")
        self.assertEqual(payload["photo"], self.IMAGE_URL)
        self.assertEqual(payload["caption"], "<b>Sinyal BTC</b>")
        self.assertEqual(payload["parse_mode"], "HTML")

    def test_long_caption_truncated_and_full_text_sent_via_message(self):
        long_text = "<b>X</b>" * 500
        with mock.patch("telegram_sender.requests.post") as post:
            post.return_value = self._mock_post()
            send_telegram(long_text, image_url=self.IMAGE_URL)

        urls = [call.args[0] for call in post.call_args_list]
        self.assertEqual(len(urls), 2)
        photo_payload = post.call_args_list[0].kwargs["json"]
        self.assertIn("/sendPhoto", urls[0])
        self.assertLessEqual(len(photo_payload["caption"]), PHOTO_CAPTION_MAX)
        message_payload = post.call_args_list[1].kwargs["json"]
        self.assertIn("/sendMessage", urls[1])
        self.assertEqual(message_payload["text"], long_text)

    def test_photo_failure_falls_back_to_full_text_message(self):
        with mock.patch("telegram_sender.requests.post") as post:
            post.side_effect = [self._mock_post(status=400), self._mock_post()]
            send_telegram("teks sinyal penting", image_url=self.IMAGE_URL)

        urls = [call.args[0] for call in post.call_args_list]
        self.assertEqual(len(urls), 2)
        self.assertIn("/sendPhoto", urls[0])
        self.assertIn("/sendMessage", urls[1])
        message_payload = post.call_args_list[1].kwargs["json"]
        self.assertEqual(message_payload["text"], "teks sinyal penting")

    def test_no_image_uses_sendmessage(self):
        with mock.patch("telegram_sender.requests.post") as post:
            post.return_value = self._mock_post()
            send_telegram("<b>tanpa gambar</b>")
        self.assertEqual(post.call_count, 1)
        self.assertIn("/sendMessage", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["json"]["text"], "<b>tanpa gambar</b>")

    def test_send_telegram_photo_direct(self):
        with mock.patch("telegram_sender.requests.post") as post:
            post.return_value = self._mock_post()
            send_telegram_photo(self.IMAGE_URL, "caption pendek")
        self.assertIn("/sendPhoto", post.call_args.args[0])

    def test_photo_without_chat_id_raises(self):
        with mock.patch("telegram_sender.TELEGRAM_CHAT_ID", ""):
            with mock.patch("telegram_sender.requests.post") as post:
                with self.assertRaises(TelegramSendError):
                    send_telegram("teks", image_url=self.IMAGE_URL)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
