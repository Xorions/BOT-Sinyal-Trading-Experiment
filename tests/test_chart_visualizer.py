"""Tes unit visualizer chart TradingView (execution/chart_visualizer.py).

Semua request HTTP di-mock agar tidak memakan kuota API ChartImg.
"""

import unittest
from unittest import mock

import requests

from execution.chart_visualizer import (
    CHART_IMG_API_URL,
    _chartimg_interval,
    generate_chart_url,
)

STORAGE_URL = "https://r2.chart-img.com/tradingview/advanced-chart/snapshot/abc123.png"


def _fake_response(status=200, payload=None, exc=None):
    resp = mock.Mock()
    resp.status_code = status
    if exc is not None:
        resp.raise_for_status.side_effect = exc
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = payload if payload is not None else {"url": STORAGE_URL}
    return resp


class TestGenerateChartUrl(unittest.TestCase):
    def setUp(self):
        self._key = mock.patch("execution.chart_visualizer.CHART_IMG_API_KEY", "test-key")
        self._key.start()

    def tearDown(self):
        self._key.stop()

    def test_returns_storage_url_and_builds_payload(self):
        with mock.patch("execution.chart_visualizer.requests.post") as post:
            post.return_value = _fake_response()
            url = generate_chart_url("BTC", "BUY", 100.0, 95.0, 105.0, 110.0)

        self.assertEqual(url, STORAGE_URL)
        kwargs = post.call_args.kwargs
        self.assertEqual(post.call_args.args[0], CHART_IMG_API_URL)
        self.assertEqual(kwargs["headers"]["x-api-key"], "test-key")
        self.assertEqual(kwargs["headers"]["content-type"], "application/json")

        body = kwargs["json"]
        self.assertEqual(body["symbol"], "BINANCE:BTCUSDT")
        self.assertEqual(body["interval"], "1h")
        self.assertEqual(body["theme"], "dark")
        self.assertEqual(body["format"], "png")
        self.assertIn("from", body["range"])
        self.assertIn("to", body["range"])

        position, tp2 = body["drawings"]
        self.assertEqual(position["name"], "Long Position")
        self.assertEqual(position["input"]["entryPrice"], 100.0)
        self.assertEqual(position["input"]["stopPrice"], 95.0)
        self.assertEqual(position["input"]["targetPrice"], 105.0)
        self.assertIn("startDatetime", position["input"])
        self.assertEqual(tp2["name"], "Horizontal Line")
        self.assertEqual(tp2["input"]["price"], 110.0)
        self.assertIn("TP2", tp2["input"]["text"])

    def test_sell_uses_short_position_drawing(self):
        with mock.patch("execution.chart_visualizer.requests.post") as post:
            post.return_value = _fake_response()
            generate_chart_url("ETH", "SELL", 2000.0, 2050.0, 1950.0, 1900.0)

        position = post.call_args.kwargs["json"]["drawings"][0]
        self.assertEqual(position["name"], "Short Position")
        self.assertEqual(position["input"]["entryPrice"], 2000.0)
        self.assertEqual(position["input"]["stopPrice"], 2050.0)
        self.assertEqual(position["input"]["targetPrice"], 1950.0)

    def test_timeframe_passed_through(self):
        with mock.patch("execution.chart_visualizer.requests.post") as post:
            post.return_value = _fake_response()
            generate_chart_url(
                "SOL", "BUY", 150.0, 145.0, 155.0, 160.0, timeframe="4H"
            )
        self.assertEqual(post.call_args.kwargs["json"]["interval"], "4h")

    def test_missing_api_key_returns_none_without_request(self):
        with mock.patch("execution.chart_visualizer.CHART_IMG_API_KEY", ""):
            with mock.patch("execution.chart_visualizer.requests.post") as post:
                url = generate_chart_url("BTC", "BUY", 100.0, 95.0, 105.0, 110.0)
        self.assertIsNone(url)
        post.assert_not_called()

    def test_invalid_levels_return_none(self):
        with mock.patch("execution.chart_visualizer.requests.post") as post:
            url = generate_chart_url("BTC", "BUY", 100.0, 0.0, 105.0, 110.0)
            self.assertIsNone(url)
            url = generate_chart_url("BTC", "BUY", 100.0, 95.0, None, 110.0)
            self.assertIsNone(url)
        post.assert_not_called()

    def test_empty_symbol_returns_none(self):
        with mock.patch("execution.chart_visualizer.requests.post") as post:
            url = generate_chart_url("", "BUY", 100.0, 95.0, 105.0, 110.0)
        self.assertIsNone(url)
        post.assert_not_called()

    def test_http_error_returns_none(self):
        with mock.patch("execution.chart_visualizer.requests.post") as post:
            post.return_value = _fake_response(
                status=403, exc=requests.HTTPError("Forbidden")
            )
            url = generate_chart_url("BTC", "BUY", 100.0, 95.0, 105.0, 110.0)
        self.assertIsNone(url)

    def test_network_error_returns_none(self):
        with mock.patch("execution.chart_visualizer.requests.post") as post:
            post.side_effect = requests.ConnectionError("network down")
            url = generate_chart_url("BTC", "BUY", 100.0, 95.0, 105.0, 110.0)
        self.assertIsNone(url)

    def test_response_without_url_returns_none(self):
        with mock.patch("execution.chart_visualizer.requests.post") as post:
            post.return_value = _fake_response(payload={"etag": "x"})
            url = generate_chart_url("BTC", "BUY", 100.0, 95.0, 105.0, 110.0)
        self.assertIsNone(url)

    def test_invalid_json_returns_none(self):
        with mock.patch("execution.chart_visualizer.requests.post") as post:
            post.return_value = _fake_response()
            post.return_value.json.side_effect = ValueError("no json")
            url = generate_chart_url("BTC", "BUY", 100.0, 95.0, 105.0, 110.0)
        self.assertIsNone(url)


class TestIntervalNormalization(unittest.TestCase):
    def test_intraday_stays_lowercase(self):
        self.assertEqual(_chartimg_interval("1h"), "1h")
        self.assertEqual(_chartimg_interval("15M"), "15m")
        self.assertEqual(_chartimg_interval("4H"), "4h")

    def test_daily_weekly_uppercase_suffix(self):
        self.assertEqual(_chartimg_interval("1D"), "1D")
        self.assertEqual(_chartimg_interval("1d"), "1D")
        self.assertEqual(_chartimg_interval("2d"), "2D")
        self.assertEqual(_chartimg_interval("1w"), "1W")

    def test_unknown_falls_back_to_1h(self):
        self.assertEqual(_chartimg_interval("xyz"), "1h")
        self.assertEqual(_chartimg_interval(""), "1h")


if __name__ == "__main__":
    unittest.main()