"""Tes unit untuk execution/okx_executor.py (FakeExchange, tanpa network).

Memverifikasi:
- konversi simbol -> pair USDT-M
- risk-based position sizing (1% free balance)
- alur market order + SL terpasang + TP1 50% / TP2 50% reduce-only
- params khas OKX: tdMode='cross' pada semua order swap
- handling kegagalan (saldo 0, simbol tidak tersedia, kredensial kosong)
"""

import unittest
from unittest import mock

from execution.okx_executor import (
    OKX_TD_MODE,
    OkxExecutionError,
    build_exchange,
    execute_signal,
    fetch_free_balance_usdt,
    market_symbol,
    position_quantity,
    risk_amount_usd,
)
from signals.engine import ACTION_BUY, ACTION_SELL, Signal


class FakeMarket:
    def __init__(self, symbol="BTC/USDT:USDT", contract_size=1.0):
        self.symbol = symbol
        self.contractSize = contract_size
        self.base = symbol.split("/")[0]

    def get(self, key, default=None):
        return getattr(self, key, default)


class FakeExchange:
    """Simulasi minimal ccxt.okx: mencatat semua panggilan order."""

    def __init__(self, free_usdt=1000.0, contract_size=1.0, symbol="BTC/USDT:USDT"):
        self.free_usdt = free_usdt
        self.contract_size = contract_size
        self.symbol = symbol
        self.orders = []

    def market(self, symbol):
        if symbol != self.symbol:
            raise ValueError(f"BadSymbol: {symbol}")
        return FakeMarket(self.symbol, self.contract_size)

    def amount_to_precision(self, symbol, amount):
        return f"{float(amount):.4f}"

    def price_to_precision(self, symbol, price):
        return f"{float(price):.2f}"

    def fetch_balance(self, params=None):
        return {"USDT": {"free": self.free_usdt}}

    def create_order(self, symbol, order_type, side, amount, price, params=None):
        params = dict(params or {})
        self.orders.append(
            {
                "symbol": symbol,
                "type": order_type,
                "side": side,
                "amount": float(amount),
                "price": price,
                "params": params,
            }
        )
        return {"id": f"order-{len(self.orders)}"}


def _signal(action=ACTION_BUY, symbol="BTC", entry=100.0, sl=95.0, tp1=105.0, tp2=110.0):
    return Signal(
        coin_id="bitcoin",
        symbol=symbol,
        name="Bitcoin",
        price=entry,
        price_change_24h=2.0,
        score=5.0,
        action=action,
        confidence=85,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
    )


class TestMarketSymbol(unittest.TestCase):
    def test_converts_coin_to_usdtm_pair(self):
        self.assertEqual(market_symbol("btc"), "BTC/USDT:USDT")
        self.assertEqual(market_symbol("Doge"), "DOGE/USDT:USDT")
        self.assertEqual(market_symbol("BTC/USDT:USDT"), "BTC/USDT:USDT")


class TestRiskSizing(unittest.TestCase):
    def test_risk_amount_is_one_percent_of_free_balance(self):
        self.assertAlmostEqual(risk_amount_usd(10_000.0), 100.0)

    def test_position_quantity_long(self):
        self.assertAlmostEqual(position_quantity(100.0, 95.0, 10.0), 2.0)

    def test_position_quantity_short_uses_abs_distance(self):
        self.assertAlmostEqual(position_quantity(100.0, 105.0, 10.0), 2.0)

    def test_invalid_levels_raise(self):
        with self.assertRaises(OkxExecutionError):
            position_quantity(100.0, 100.0, 10.0)
        with self.assertRaises(OkxExecutionError):
            position_quantity(0.0, 95.0, 10.0)


class TestBalance(unittest.TestCase):
    def test_zero_balance_raises(self):
        ex = FakeExchange(free_usdt=0.0)
        with self.assertRaises(OkxExecutionError):
            fetch_free_balance_usdt(ex)

    def test_returns_free_usdt(self):
        self.assertEqual(fetch_free_balance_usdt(FakeExchange(250.5)), 250.5)


class TestExecuteBuy(unittest.TestCase):
    def test_market_order_with_sl_and_split_tp(self):
        ex = FakeExchange(free_usdt=1000.0)
        report = execute_signal(ex, _signal())  # risk 10, entry 100, sl 95 -> 2 koin

        self.assertEqual(len(ex.orders), 3)
        entry, tp1, tp2 = ex.orders

        self.assertEqual(entry["type"], "market")
        self.assertEqual(entry["side"], "buy")
        self.assertAlmostEqual(entry["amount"], 2.0)
        self.assertEqual(entry["params"]["stopLossPrice"], "95.00")

        self.assertEqual(tp1["type"], "limit")
        self.assertEqual(tp1["side"], "sell")
        self.assertAlmostEqual(tp1["amount"], 1.0)  # 50%
        self.assertEqual(tp1["price"], "105.00")
        self.assertTrue(tp1["params"]["reduceOnly"])

        self.assertEqual(tp2["type"], "limit")
        self.assertEqual(tp2["side"], "sell")
        self.assertAlmostEqual(tp2["amount"], 1.0)  # 50%
        self.assertEqual(tp2["price"], "110.00")
        self.assertTrue(tp2["params"]["reduceOnly"])

        self.assertEqual(report["order_id"], "order-1")
        self.assertEqual(report["tp1_order_id"], "order-2")
        self.assertEqual(report["tp2_order_id"], "order-3")

    def test_all_orders_use_cross_td_mode(self):
        ex = FakeExchange(free_usdt=1000.0)
        execute_signal(ex, _signal())

        for order in ex.orders:
            self.assertEqual(order["params"]["tdMode"], "cross")
        self.assertEqual(OKX_TD_MODE, "cross")


class TestExecuteSell(unittest.TestCase):
    def test_sides_reversed_and_sl_above_entry(self):
        ex = FakeExchange(free_usdt=1000.0)
        signal = _signal(action=ACTION_SELL, entry=100.0, sl=105.0, tp1=95.0, tp2=90.0)
        execute_signal(ex, signal)

        entry, tp1, tp2 = ex.orders
        self.assertEqual(entry["side"], "sell")
        self.assertEqual(entry["params"]["stopLossPrice"], "105.00")
        self.assertEqual(tp1["side"], "buy")
        self.assertEqual(tp1["price"], "95.00")
        self.assertEqual(tp2["side"], "buy")
        self.assertEqual(tp2["price"], "90.00")


class TestContractSize(unittest.TestCase):
    def test_amount_converted_to_contracts(self):
        # OKX BTC-USDT-SWAP contractSize = 0.01 BTC: 2 koin / 0.01 = 200 kontrak
        ex = FakeExchange(free_usdt=1000.0, contract_size=0.01)
        report = execute_signal(ex, _signal())

        self.assertEqual(len(ex.orders), 3)
        entry = ex.orders[0]
        self.assertAlmostEqual(entry["amount"], 200.0)
        self.assertAlmostEqual(report["amount_contracts"], 200.0)


class TestExecutionFailures(unittest.TestCase):
    def test_unsupported_symbol_raises(self):
        ex = FakeExchange(symbol="BTC/USDT:USDT")
        with self.assertRaises(OkxExecutionError) as ctx:
            execute_signal(ex, _signal(symbol="ZZZ"))
        self.assertIn("ZZZ/USDT:USDT", str(ctx.exception))

    def test_neutral_action_rejected(self):
        ex = FakeExchange()
        with self.assertRaises(OkxExecutionError):
            execute_signal(ex, _signal(action="NEUTRAL"))

    def test_entry_order_rejected_wraps_error(self):
        ex = FakeExchange()

        def boom(*args, **kwargs):
            raise RuntimeError("insufficient margin")

        with mock.patch.object(ex, "create_order", side_effect=boom):
            with self.assertRaises(OkxExecutionError) as ctx:
                execute_signal(ex, _signal())
        self.assertIn("ditolak", str(ctx.exception))

    def test_notional_capped_to_free_balance(self):
        # sl sangat dekat -> koin besar -> dibatasi agar margin 1x cukup.
        ex = FakeExchange(free_usdt=500.0)
        signal = _signal(entry=100.0, sl=99.999)  # ~10k koin tanpa cap
        report = execute_signal(ex, signal)
        entry = ex.orders[0]
        self.assertLessEqual(entry["amount"], 5.0 + 1e-6)  # 500/100 = 5 maks
        self.assertEqual(report["amount_contracts"], entry["amount"])

    def test_balance_not_fetched_when_zero(self):
        ex = FakeExchange(free_usdt=0.0)
        with self.assertRaises(OkxExecutionError):
            execute_signal(ex, _signal())


class TestBuildExchange(unittest.TestCase):
    def test_missing_credentials_raise(self):
        with mock.patch("execution.okx_executor.OKX_API_KEY", ""), mock.patch(
            "execution.okx_executor.OKX_SECRET_KEY", ""
        ), mock.patch("execution.okx_executor.OKX_PASSPHRASE", ""):
            with self.assertRaises(OkxExecutionError) as ctx:
                build_exchange()
        self.assertIn(".env", str(ctx.exception))

    def test_creates_swap_exchange(self):
        with mock.patch("execution.okx_executor.ccxt.okx") as okx_cls, mock.patch(
            "execution.okx_executor.OKX_API_KEY", "k"
        ), mock.patch(
            "execution.okx_executor.OKX_SECRET_KEY", "s"
        ), mock.patch(
            "execution.okx_executor.OKX_PASSPHRASE", "p"
        ):
            okx_cls.return_value.load_markets = mock.Mock()
            exchange = build_exchange()
            config = okx_cls.call_args[0][0]
            self.assertEqual(config["options"]["defaultType"], "swap")
            self.assertEqual(config["options"]["adjustForTimeDifference"], True)
            self.assertEqual(config["password"], "p")
            self.assertEqual(exchange, okx_cls.return_value)
            okx_cls.return_value.load_markets.assert_called_once()


if __name__ == "__main__":
    unittest.main()