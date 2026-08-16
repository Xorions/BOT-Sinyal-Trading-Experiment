"""Visualisasi chart TradingView untuk notifikasi sinyal (CHART-IMG API v2).

Fungsi utama `generate_chart_url()` menghasilkan URL publik gambar chart
TradingView PNG dengan level Entry / SL / TP1 / TP2 yang tergambar jelas:

- Level Entry + SL + TP1 digambar sebagai posisi "Long/Short Position"
  (area hijau zona profit, area merah zona stop) milik TradingView.
- Level TP2 digambar sebagai garis horizontal hijau berlabel "TP2".

Fallback aman: bila `CHART_IMG_API_KEY` kosong, level harga tidak valid,
request gagal, atau respons tidak memuat URL, fungsi mengembalikan `None`
sehingga bot tetap mengirim sinyal berupa teks biasa tanpa crash.

Endpoint: POST https://api.chart-img.com/v2/tradingview/advanced-chart/storage
Header  : x-api-key
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from config import CHART_IMG_API_KEY, REQUEST_TIMEOUT

log = logging.getLogger("signal-bot.chart")

CHART_IMG_API_URL = "https://api.chart-img.com/v2/tradingview/advanced-chart/storage"
# Bursa crypto yang dicoba secara berurutan untuk simbol sinyal (USDT pairs).
# Sinyal berasal dari top koin CoinGecko yang tidak selalu terdaftar di
# Binance, jadi coba bursa mayor dulu, lalu fallback ke bursa lain.
CHART_IMG_EXCHANGES = [
    "BINANCE",
    "BYBIT",
    "OKX",
    "KUCOIN",
    "GATEIO",
    "BITGET",
    "MEXC",
    "HTX",
    "POLONIEX",
    "COINBASE",
    "CRYPTO",
]

# Konversi timeframe -> jam per bar (dipakai menghitung rentang visible chart).
_INTERVAL_HOURS = {
    "1m": 1 / 60,
    "3m": 3 / 60,
    "5m": 5 / 60,
    "10m": 10 / 60,
    "15m": 15 / 60,
    "30m": 30 / 60,
    "45m": 45 / 60,
    "1h": 1,
    "2h": 2,
    "3h": 3,
    "4h": 4,
    "6h": 6,
    "8h": 8,
    "12h": 12,
    "1d": 24,
    "2d": 48,
    "3d": 72,
    "1w": 168,
}

# Maksimal bar yang dirender (batas ChartImg ~1000 bar, kita sisakan margin).
_MAX_RANGE_BARS = 700
_MAX_RANGE_DAYS = 7


def _normalize_timeframe(timeframe: str) -> str:
    """Normalisasi timeframe ('1H', '15M', '1D', ...) ke bentuk internal."""
    tf = (timeframe or "1h").strip().lower()
    if tf == "d":
        tf = "1d"
    if tf not in _INTERVAL_HOURS:
        log.warning("Timeframe %r tidak didukung, fallback ke 1h.", timeframe)
        tf = "1h"
    return tf


def _chartimg_interval(timeframe: str) -> str:
    """Format interval sesuai spesifikasi ChartImg (intraday huruf kecil, D/W huruf besar)."""
    tf = _normalize_timeframe(timeframe)
    if tf in ("1d", "2d", "3d"):
        return tf[0] + "D"
    if tf == "1w":
        return "1W"
    return tf


def _range_days(timeframe: str) -> int:
    """Jumlah hari visible chart agar ≤ ~700 bar dari sekarang."""
    hours = _INTERVAL_HOURS[_normalize_timeframe(timeframe)]
    return max(1, min(_MAX_RANGE_DAYS, int(_MAX_RANGE_BARS * hours / 24)))


def _position_drawing(
    direction: str, entry: float, sl: float, tp1: float, start_dt: str
) -> dict:
    """Drawing Long/Short Position TradingView: entry, SL, dan TP1 sekaligus."""
    is_long = direction.upper() in ("BUY", "LONG")
    return {
        "name": "Long Position" if is_long else "Short Position",
        "input": {
            "startDatetime": start_dt,
            "entryPrice": entry,
            "targetPrice": tp1,
            "stopPrice": sl,
        },
        "override": {
            "fontSize": 13,
            "lineWidth": 2,
            "showPrice": True,
            "showStats": False,
        },
    }


def _tp2_drawing(tp2: float) -> dict:
    """Drawing garis horizontal berlabel TP2 (level take-profit kedua)."""
    return {
        "name": "Horizontal Line",
        "input": {"price": tp2, "text": "TP2"},
        "override": {
            "fontSize": 13,
            "fontBold": True,
            "lineWidth": 3,
            "lineStyle": 2,
            "lineColor": "rgb(34,171,148)",
            "textColor": "rgb(34,171,148)",
            "horzLabelAlign": "right",
        },
    }


def generate_chart_url(
    symbol: str,
    direction: str,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    timeframe: str = "1h",
) -> Optional[str]:
    """URL gambar chart TradingView dengan level Entry/SL/TP, atau None bila gagal.

    Args:
        symbol: Kode aset tanpa akhiran USDT (contoh: "BTC").
        direction: Arah sinyal ("BUY" / "SELL").
        entry: Harga entry.
        sl: Harga stop loss.
        tp1: Harga take profit pertama.
        tp2: Harga take profit kedua.
        timeframe: Timeframe chart (default "1h").

    Returns:
        URL publik gambar PNG (dari public storage ChartImg), atau None.
    """
    api_key = (CHART_IMG_API_KEY or "").strip()
    if not api_key:
        log.warning("CHART_IMG_API_KEY kosong — gambar chart dilewati (fallback teks).")
        return None

    symbol = (symbol or "").strip().upper()
    if not symbol:
        log.warning("Simbol kosong — gambar chart dilewati.")
        return None

    levels = [entry, sl, tp1, tp2]
    if any(not isinstance(value, (int, float)) or value <= 0 for value in levels):
        log.warning("Level harga tidak valid untuk %s — gambar chart dilewati.", symbol)
        return None

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=_range_days(timeframe))
    start_dt = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to_dt = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    payload = {
        "interval": _chartimg_interval(timeframe),
        "theme": "dark",
        "width": 800,
        "height": 450,
        "format": "png",
        "range": {"from": start_dt, "to": to_dt},
        "drawings": [
            _position_drawing(direction, entry, sl, tp1, start_dt),
            _tp2_drawing(tp2),
        ],
    }

    for exchange in CHART_IMG_EXCHANGES:
        payload["symbol"] = f"{exchange}:{symbol}USDT"
        try:
            resp = requests.post(
                CHART_IMG_API_URL,
                headers={"x-api-key": api_key, "content-type": "application/json"},
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 422:
                log.warning(
                    "Simbol %s tidak ada di %s — coba bursa berikutnya.",
                    symbol,
                    exchange,
                )
                continue
            resp.raise_for_status()
            data = resp.json()
            url = (data or {}).get("url")
            if not url:
                log.warning(
                    "ChartImg merespons tanpa URL untuk %s di %s — fallback teks.",
                    symbol,
                    exchange,
                )
                return None
            if exchange != CHART_IMG_EXCHANGES[0]:
                log.info("Chart %s dibuat di bursa %s.", symbol, exchange)
            return str(url)
        except (requests.RequestException, ValueError) as exc:
            log.warning(
                "Gagal membuat chart %s via ChartImg di %s (%s) — fallback teks.",
                symbol,
                exchange,
                exc,
            )
            return None

    log.warning(
        "Simbol %s tidak ditemukan di bursa mana pun (%s) — fallback teks.",
        symbol,
        ", ".join(CHART_IMG_EXCHANGES),
    )
    return None