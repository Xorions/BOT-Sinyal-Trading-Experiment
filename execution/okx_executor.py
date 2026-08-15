"""Eksekusi sinyal BUY/SELL yang lolos filter ketat ke OKX Futures (USDT-M).

Modul TERPISAH dari mesin sinyal harian — tidak mengubah logic scan.
Alur per sinyal:
1. Bangun exchange ccxt.okx dengan kredensial dari .env.
2. Hitung position size dinamis: risiko = RISK_PERCENT_PER_TRADE% dari
   free balance USDT (jarak Entry→SL menentukan jumlah koin).
3. Market order entry + SL terpasang pada order (full position) +
   TP1 (50%) & TP2 (50%) sebagai reduce-only limit order.
4. Kembalikan laporan dict untuk notifikasi admin (dikirim oleh caller).

CATATAN OKX:
- Mode akun: cross margin (tdMode='cross'). SL terpasang via attachAlgoOrds
  (ccxt mengubah params stopLossPrice menjadi algo order SL market).
- Contract size OKX USDT-M swap < 1 koin (mis. BTC-USDT-SWAP = 0.01 BTC),
  maka jumlah koin dikonversi ke jumlah kontrak sebelum order.

CATATAN KEAMANAN:
- Modul ini TIDAK melakukan apa pun jika ENABLE_OKX_AUTOTRADE=false
  (switch dicek oleh caller bot.py; fungsi safe di sini tetap eksplisit).
- Semua kegagalan API dibungkus OkxExecutionError dengan pesan jelas
  agar tidak menimbulkan gangguan pada bot sinyal harian.
"""

import logging

import ccxt

from config import (
    OKX_API_KEY,
    OKX_PASSPHRASE,
    OKX_SECRET_KEY,
    REQUEST_TIMEOUT,
    RISK_PERCENT_PER_TRADE,
)

log = logging.getLogger("okx-executor")

# Mode akun untuk order swap USDT-M: cross margin (1x, nilai posisi <= saldo).
OKX_TD_MODE = "cross"


class OkxExecutionError(Exception):
    """Gagal mengeksekusi order di OKX (saldo, API, simbol, dsb)."""


def is_enabled() -> bool:
    """True bila autotrade OKX diaktifkan lewat .env."""
    from config import ENABLE_OKX_AUTOTRADE

    return ENABLE_OKX_AUTOTRADE


def build_exchange() -> ccxt.okx:
    """Buat instance ccxt.okx untuk USDT-M Perpetual, lalu load markets."""
    if not all((OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE)):
        raise OkxExecutionError(
            "Kredensial OKX belum diisi di .env "
            "(OKX_API_KEY / OKX_SECRET_KEY / OKX_PASSPHRASE)."
        )
    exchange = ccxt.okx(
        {
            "apiKey": OKX_API_KEY,
            "secret": OKX_SECRET_KEY,
            "password": OKX_PASSPHRASE,
            "enableRateLimit": True,
            "timeout": REQUEST_TIMEOUT * 1000,
            "options": {
                "defaultType": "swap",
                "adjustForTimeDifference": True,
            },
        }
    )
    try:
        exchange.load_markets()
    except ccxt.NetworkError as exc:
        raise OkxExecutionError(f"Gagal hubungi OKX (load_markets): {exc}") from exc
    return exchange


def market_symbol(symbol: str) -> str:
    """Konversi simbol koin -> pair USDT-M Perpetual (mis. 'BTC' -> 'BTC/USDT:USDT')."""
    base = symbol.upper().split("/")[0].split(":")[0]
    return f"{base}/USDT:USDT"


def fetch_free_balance_usdt(exchange) -> float:
    """Free balance USDT di akun Futures (swap). Raise bila 0 / gagal API."""
    try:
        balance = exchange.fetch_balance({"type": "swap", "code": "USDT"})
    except ccxt.BaseError as exc:
        raise OkxExecutionError(f"Gagal fetch balance USDT: {exc}") from exc
    free = float((balance.get("USDT") or {}).get("free", 0.0))
    if free <= 0:
        raise OkxExecutionError(
            "Saldo free USDT = 0 di akun Futures — tidak cukup untuk memasang order."
        )
    return free


def risk_amount_usd(free_balance: float) -> float:
    """Jumlah dolar yang dipertaruhkan per trade (persen dari saldo free)."""
    return free_balance * RISK_PERCENT_PER_TRADE / 100.0


def position_quantity(entry: float, sl: float, risk_usd: float) -> float:
    """Jumlah koin dari risk-based sizing.

    LONG  (BUY):  risiko = (entry - SL) per koin  →  koin = risk_usd / (entry - SL)
    SHORT (SELL): risiko = (SL - entry) per koin  →  koin = risk_usd / (SL - entry)
    """
    distance = abs(entry - sl)
    if entry <= 0 or sl <= 0 or distance <= 0:
        raise OkxExecutionError("Entry/SL sinyal tidak valid untuk position sizing.")
    return risk_usd / distance


def _contract_amount(exchange, symbol: str, coins: float, max_coins: float) -> float:
    """Konversi koin -> kontrak (per contractSize market) + batasi notional."""
    capped = min(coins, max_coins) if max_coins > 0 else coins
    if capped <= 0:
        raise OkxExecutionError("Position size hasil perhitungan = 0.")
    market = exchange.market(symbol)
    contract_size = float(market.get("contractSize") or 1.0)
    contracts = capped / contract_size
    return exchange.amount_to_precision(symbol, contracts)


def _to_float(value) -> float:
    return float(value)


def _order_params(base: dict) -> dict:
    """Params umum semua order OKX swap: tdMode wajib (cross margin)."""
    return {"tdMode": OKX_TD_MODE, **base}


def execute_signal(exchange, signal) -> dict:
    """Eksekusi satu sinyal (BUY/SELL) dengan SL + TP1 50% + TP2 50%.

    `signal` perlu atribut: symbol, action, price (entry), sl, tp1, tp2.
    Mengembalikan dict laporan untuk notifikasi. Raise OkxExecutionError.
    """
    if signal.action not in ("BUY", "SELL"):
        raise OkxExecutionError(f"Action sinyal tidak valid untuk eksekusi: {signal.action}")

    symbol = market_symbol(signal.symbol)
    side = "buy" if signal.action == "BUY" else "sell"
    tp_side = "sell" if side == "buy" else "buy"

    entry = _to_float(signal.price)
    sl = _to_float(signal.sl)
    tp1 = _to_float(signal.tp1)
    tp2 = _to_float(signal.tp2)

    try:
        market = exchange.market(symbol)
    except Exception as exc:  # noqa: BLE001 - simulasi ccxt.BadSymbol dll.
        raise OkxExecutionError(
            f"Simbol {symbol} tidak ditemukan di OKX Futures ({exc})."
        ) from exc

    free_balance = fetch_free_balance_usdt(exchange)
    risk_usd = risk_amount_usd(free_balance)
    coins = position_quantity(entry, sl, risk_usd)

    # Batas aman: nilai posisi (coin × entry) tidak melebihi saldo (margin 1x).
    max_coins = free_balance / entry if entry > 0 else 0.0
    amount = _contract_amount(exchange, symbol, coins, max_coins)
    half = exchange.amount_to_precision(
        symbol, _to_float(amount) / 2.0 if _to_float(amount) > 0 else 0.0
    )

    sl_price = exchange.price_to_precision(symbol, sl)
    tp1_price = exchange.price_to_precision(symbol, tp1)
    tp2_price = exchange.price_to_precision(symbol, tp2)

    result = {
        "symbol": market.get("base") or symbol.split("/")[0],
        "action": signal.action,
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "free_balance": free_balance,
        "risk_usd": risk_usd,
        "amount_coins": coins,
        "amount_contracts": _to_float(amount),
        "tp1_amount_contracts": _to_float(half),
        "tp2_amount_contracts": _to_float(half),
        "sl_price": sl_price,
        "tp1_price": tp1_price,
        "tp2_price": tp2_price,
        "order_id": "",
        "tp1_order_id": "",
        "tp2_order_id": "",
    }

    # 1) Market order entry + SL terpasang langsung (full position).
    #    OKX: stopLossPrice diubah ccxt menjadi algo SL market (attachAlgoOrds).
    try:
        order = exchange.create_order(
            symbol,
            "market",
            side,
            amount,
            None,
            _order_params({"stopLossPrice": sl_price}),
        )
    except Exception as exc:  # noqa: BLE001 - wrap error API apa pun agar laporan admin jelas
        raise OkxExecutionError(f"Order entry {symbol} ditolak: {exc}") from exc
    result["order_id"] = str(order.get("id") or "")

    # 2) TP1 50% & TP2 50%: reduce-only limit agar hanya menutup posisi.
    try:
        tp1_order = exchange.create_order(
            symbol,
            "limit",
            tp_side,
            half,
            tp1_price,
            _order_params({"reduceOnly": True}),
        )
        result["tp1_order_id"] = str(tp1_order.get("id") or "")
    except Exception as exc:  # noqa: BLE001 - TP gagal tidak membatalkan entry
        log.error("TP1 %s gagal dipasang: %s", symbol, exc)

    try:
        tp2_order = exchange.create_order(
            symbol,
            "limit",
            tp_side,
            half,
            tp2_price,
            _order_params({"reduceOnly": True}),
        )
        result["tp2_order_id"] = str(tp2_order.get("id") or "")
    except Exception as exc:  # noqa: BLE001
        log.error("TP2 %s gagal dipasang: %s", symbol, exc)

    log.info(
        "Order %s %s %s | %s kontrak | SL %s | TP1 %s (50%%) | TP2 %s (50%%)",
        side.upper(),
        symbol,
        result["order_id"],
        amount,
        sl_price,
        tp1_price,
        tp2_price,
    )
    return result