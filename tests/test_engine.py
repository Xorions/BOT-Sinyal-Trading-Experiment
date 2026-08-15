"""Tes unit untuk signals/engine.py: analisis MTF (dengan mock data) + format."""

import unittest
from unittest import mock

import config
from signals.engine import (
    ACTION_BUY,
    ACTION_SELL,
    MTFResult,
    Signal,
    analyze_mtf,
    build_checklist,
    build_final_signal,
    format_message,
    signal_levels,
)

BASE_TS = 1_700_000_000_000  # ms


def _series(prices, volumes):
    """Seri `[ts_ms, value]` 1 jam per titik, dimulai dari BASE_TS."""
    return [
        [BASE_TS + i * 3600 * 1000, price] for i, price in enumerate(prices)
    ], [
        [BASE_TS + i * 3600 * 1000, volume] for i, volume in enumerate(volumes)
    ]


def _chart(prices, volumes):
    price_series, volume_series = _series(prices, volumes)
    return {"prices": price_series, "total_volumes": volume_series}


def _trend_prices(start, end, count, noise=0.002):
    step = (end - start) / (count - 1)
    return [start + step * i * (1 + (i % 5) * noise) for i in range(count)]


def _uptrend_chart():
    return _chart(_trend_prices(100, 220, 720), [1000 + (i % 7) * 10 for i in range(720)])


def _downtrend_chart():
    return _chart(_trend_prices(220, 80, 720), [1000 + (i % 7) * 10 for i in range(720)])


def _quick_signal(coin_id="bitcoin", score=3.5, price=150.0, action=ACTION_BUY):
    return Signal(
        coin_id=coin_id,
        symbol="BTC",
        name="Bitcoin",
        price=price,
        price_change_24h=2.0,
        score=score,
        action=action,
        confidence=70,
    )


def _bullish_mtf(coin_id="bitcoin"):
    return MTFResult(
        coin_id=coin_id,
        ht_bias="BULLISH",
        bos_kind="BOS",
        bos_direction="BULL",
        ob_bullish=True,
        ob_bearish=False,
        support=140.0,
        resistance=200.0,
        near_support=False,
        near_resistance=False,
        demand_zone=False,
        supply_zone=False,
        macd_cross="BULLISH_CROSS",
        rsi_value=58.0,
        rsi_div="",
        rsi_bull_aligned=True,
        rsi_bear_aligned=False,
        whale_bull=True,
        whale_bear=False,
        volume_ratio=3.0,
        atr_1h=2.5,
        bull_points=5.5,
        bear_points=0.0,
        bull_reasons=["HTF bias bullish (4H/1D)", "SMC: BOS bullish (LTF)"],
        bear_reasons=[],
    )


class TestAnalyzeMtf(unittest.TestCase):
    def test_uptrend_bullish(self):
        with mock.patch(
            "signals.engine.get_market_chart",
            side_effect=lambda _cid, days: _uptrend_chart(),
        ):
            result = analyze_mtf("bitcoin")
        self.assertIsNotNone(result)
        self.assertEqual(result.ht_bias, "BULLISH")
        self.assertGreater(result.bull_points, result.bear_points)

    def test_downtrend_bearish(self):
        with mock.patch(
            "signals.engine.get_market_chart",
            side_effect=lambda _cid, days: _downtrend_chart(),
        ):
            result = analyze_mtf("bitcoin")
        self.assertIsNotNone(result)
        self.assertEqual(result.ht_bias, "BEARISH")
        self.assertGreater(result.bear_points, result.bull_points)


class TestBuildFinalSignal(unittest.TestCase):
    def test_buy_with_confluence(self):
        sig = build_final_signal(_quick_signal(score=1.0), _bullish_mtf())
        self.assertEqual(sig.action, ACTION_BUY)
        self.assertGreaterEqual(sig.score, 3.0)
        self.assertEqual(sig.ht_bias, "BULLISH")
        self.assertLess(sig.sl, sig.price)
        self.assertGreater(sig.tp2, sig.price)

    def test_sl_tp_atr_levels(self):
        sig = build_final_signal(_quick_signal(score=1.0, price=100.0), _bullish_mtf())
        sl, tp1, tp2 = signal_levels(sig)
        self.assertAlmostEqual(sl, 100.0 - 2.5 * config.ATR_SL_MULT, places=6)
        self.assertAlmostEqual(tp1, 100.0 + 2.5 * config.ATR_TP1_MULT, places=6)
        self.assertAlmostEqual(tp2, 100.0 + 2.5 * config.ATR_TP2_MULT, places=6)

    def test_sl_beyond_swing_low(self):
        mtf = _bullish_mtf()
        mtf.atr_1h = 2.0
        mtf.support = 96.5
        sig = build_final_signal(_quick_signal(score=1.0, price=100.0), mtf)
        sl, _, _ = signal_levels(sig)
        atr_sl = 100.0 - 2.0 * config.ATR_SL_MULT
        swing_sl = 96.5 - 2.0 * config.SWING_SL_BUFFER_MULT
        expected = max(min(atr_sl, swing_sl), 100.0 - 2.0 * config.MAX_SL_MULT)
        self.assertAlmostEqual(sl, expected, places=6)
        self.assertLess(sl, 96.5)  # di luar swing low

    def test_sl_beyond_swing_high(self):
        mtf = _bullish_mtf()
        mtf.ht_bias = "BEARISH"
        mtf.bos_direction = "BEAR"
        mtf.ob_bullish = False
        mtf.ob_bearish = True
        mtf.demand_zone = False
        mtf.supply_zone = True
        mtf.near_support = False
        mtf.near_resistance = True
        mtf.macd_cross = "BEARISH_CROSS"
        mtf.rsi_bull_aligned = False
        mtf.rsi_bear_aligned = True
        mtf.whale_bull = False
        mtf.whale_bear = True
        mtf.bull_points = 0.0
        mtf.bear_points = 4.5
        mtf.atr_1h = 2.0
        mtf.resistance = 103.5
        sig = build_final_signal(
            _quick_signal(score=-1.0, price=100.0, action=ACTION_SELL), mtf
        )
        sl, _, _ = signal_levels(sig)
        atr_sl = 100.0 + 2.0 * config.ATR_SL_MULT
        swing_sl = 103.5 + 2.0 * config.SWING_SL_BUFFER_MULT
        expected = min(max(atr_sl, swing_sl), 100.0 + 2.0 * config.MAX_SL_MULT)
        self.assertAlmostEqual(sl, expected, places=6)
        self.assertGreater(sl, 103.5)  # di luar swing high

    def test_sl_capped_by_max_sl_mult(self):
        mtf = _bullish_mtf()
        mtf.atr_1h = 2.0
        mtf.support = 90.0  # swing sangat jauh -> SL dibatasi agar R:R tetap sehat
        sig = build_final_signal(_quick_signal(score=1.0, price=100.0), mtf)
        sl, _, _ = signal_levels(sig)
        self.assertAlmostEqual(sl, 100.0 - 2.0 * config.MAX_SL_MULT, places=6)

    def test_low_confluence_demoted_to_neutral(self):
        weak = _bullish_mtf()
        weak.ht_bias = "BULLISH"
        weak.bos_direction = "BULL"
        weak.ob_bullish = False
        weak.demand_zone = False
        weak.near_support = False
        weak.macd_cross = ""
        weak.rsi_bull_aligned = False
        weak.whale_bull = False
        weak.bull_points = 1.5  # hanya HTF bias
        sig = build_final_signal(_quick_signal(score=1.0), weak)
        self.assertEqual(sig.action, "NEUTRAL")

    def test_smc_only_without_core_demoted_to_neutral(self):
        """SMC/OB 2/2 tapi S&D/S&R & MACD/RSI 0/2 -> WATCHLIST (bukan BUY/SELL)."""
        weak = _bullish_mtf()
        weak.demand_zone = False
        weak.supply_zone = False
        weak.near_support = False
        weak.near_resistance = False
        weak.macd_cross = ""
        weak.rsi_bull_aligned = False
        weak.rsi_bear_aligned = False
        weak.whale_bull = False
        weak.whale_bear = False
        weak.bull_points = 2.0  # hanya SMC: BOS + OB
        sig = build_final_signal(_quick_signal(score=1.0), weak)
        self.assertEqual(sig.action, "NEUTRAL")
        self.assertIn("WATCHLIST", "\n".join(sig.reasons))

    def test_core_confirmed_promoted_to_buy(self):
        mtf = _bullish_mtf()  # MACD/RSI 2/2 -> lolos gate konfluensi inti
        sig = build_final_signal(_quick_signal(score=1.0), mtf)
        self.assertEqual(sig.action, ACTION_BUY)

    def test_smc_plus_core_check_promoted_to_buy(self):
        """SMC/OB 2/2 + minimal 1 cek inti (mis. near support) -> BUY valid."""
        mtf = _bullish_mtf()
        mtf.macd_cross = ""
        mtf.rsi_bull_aligned = False
        mtf.near_support = True
        mtf.demand_zone = False
        mtf.whale_bull = False
        mtf.bull_points = 3.0  # HTF 1.5 + BOS 1 + OB 1 -0.5? tetap > ambang via quick
        sig = build_final_signal(_quick_signal(score=2.5), mtf)
        self.assertEqual(sig.action, ACTION_BUY)


class TestChecklist(unittest.TestCase):
    def _mtf(self, **overrides):
        base = dict(
            coin_id="x",
            ht_bias="BULLISH",
            bos_kind="BOS",
            bos_direction="BULL",
            ob_bullish=True,
            ob_bearish=False,
            support=1.0,
            resistance=3.0,
            near_support=False,
            near_resistance=False,
            demand_zone=True,
            supply_zone=False,
            macd_cross="BULLISH_CROSS",
            rsi_value=55.0,
            rsi_div="",
            rsi_bull_aligned=True,
            rsi_bear_aligned=False,
            whale_bull=False,
            whale_bear=False,
            volume_ratio=1.0,
            atr_1h=0.05,
            bull_points=4.0,
            bear_points=0.0,
        )
        base.update(overrides)
        return MTFResult(**base)

    def test_buy_checklist_counts(self):
        checklist = build_checklist(ACTION_BUY, self._mtf())
        self.assertEqual(checklist["SMC/OB"], (2, 2))
        self.assertEqual(checklist["S&D/S&R"], (1, 2))
        self.assertEqual(checklist["MACD/RSI"], (2, 2))
        self.assertEqual(checklist["Whale/Vol"], (0, 1))

    def test_sell_checklist_reverses(self):
        mtf = self._mtf(
            ht_bias="BEARISH",
            bos_direction="BEAR",
            ob_bullish=False,
            ob_bearish=True,
            demand_zone=False,
            supply_zone=True,
            macd_cross="BEARISH_CROSS",
            rsi_bull_aligned=False,
            rsi_bear_aligned=True,
        )
        checklist = build_checklist(ACTION_SELL, mtf)
        self.assertEqual(checklist["SMC/OB"], (2, 2))
        self.assertEqual(checklist["MACD/RSI"], (2, 2))


class TestFormatMessage(unittest.TestCase):
    def test_includes_checklist_header(self):
        sig = build_final_signal(_quick_signal(), _bullish_mtf())
        body = format_message(
            [sig],
            "Sat, 08 Aug 2026, 07:00 WIB",
            250,
            session_label="Pagi (07:00 WIB)",
        )
        self.assertIn("CONFLUENCE CHECKLIST", body)
        self.assertIn("SMC/OB", body)
        self.assertIn("Whale/Vol", body)
        self.assertIn("Day Trading Signals", body)


if __name__ == "__main__":
    unittest.main()
