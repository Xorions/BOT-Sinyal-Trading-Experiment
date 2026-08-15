"""Entry point bot sinyal trading Day Trading Lanjutan.

Alur per eksekusi:
1. Quick scan top koin (satu panggilan CoinGecko) untuk shortlist kandidat.
2. Deep scan Multi-Timeframe (MTF) untuk kandidat: HTF 4H/1D (trend bias) +
   LTF 1H/15M (entry/SL/TP) + konfluensi SMC, S&D/S&R, MACD/RSI, Whale/Volume.
3. Evaluasi sinyal dari sesi sebelumnya (performance tracking).
4. Kirim pesan ke Telegram (evaluasi di atas, lalu daftar sinyal dengan
   "Confluence Checklist"), simpan sinyal sesi ini ke history.
5. Bila ENABLE_OKX_AUTOTRADE=true, sinyal BUY/SELL yang lolos filter
   dieksekusi ke OKX Futures oleh modul terpisah execution/okx_executor.py
   (laporan live ke TELEGRAM_ADMIN_CHAT_ID).

Jadwal 2x sehari (GitHub Actions): 10:00 WIB (Sesi Pagi) & 16:00 WIB (Sesi Malam).
Untuk uji lokal:  python bot.py
"""

import logging
import sys
from datetime import datetime

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (ValueError, OSError):
        pass

from config import (
    ENABLE_OKX_AUTOTRADE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TOP_COINS,
)
from data.history import (
    append_signals,
    current_session,
    format_evaluation,
    load_last_entry,
    session_label,
)
from data.market import coin_price_map, get_prices_for_ids, get_top_coins
from signals.engine import ACTION_BUY, ACTION_SELL, format_message, rank_signals
from telegram_sender import TelegramSendError, send_telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("signal-bot")


def run_scan() -> tuple:
    """Quick scan -> shortlist -> deep scan MTF -> daftar sinyal final."""
    log.info("Mengambil top %d koin dari CoinGecko...", TOP_COINS)
    coins = get_top_coins()
    log.info("Ditemukan %d koin (setelah filter stablecoin).", len(coins))

    signals = rank_signals(coins)
    log.info("Terpilih %d sinyal terbaik.", len(signals))
    for sig in signals:
        log.info(
            "Sinyal %s -> %s (skor %+.1f) | HTF %s | %s",
            sig.symbol,
            sig.action,
            sig.score,
            sig.ht_bias or "-",
            " | ".join(f"{k}:{a}/{t}" for k, (a, t) in sig.checklist.items()) or "no-MTF",
        )
    return signals, coins


def evaluate_previous_session(coins: list) -> str:
    """Evaluasi sinyal sesi sebelumnya dengan harga saat ini."""
    prev_entry = load_last_entry()
    price_map = coin_price_map(coins)
    missing_ids = [
        record.get("coin_id")
        for record in (prev_entry or {}).get("signals", [])
        if record.get("coin_id") and record.get("coin_id") not in price_map
    ]
    if missing_ids:
        try:
            price_map.update(get_prices_for_ids(missing_ids))
        except Exception as exc:  # noqa: BLE001 - evaluasi tidak boleh menggagalkan briefing
            log.warning("Gagal mengambil harga evaluasi sesi sebelumnya: %s", exc)
    return format_evaluation(prev_entry, price_map)


def run_autotrade(signals: list) -> None:
    """Eksekusi sinyal BUY/SELL valid ke OKX Futures (hanya jika diaktifkan).

    Modul terpisah `execution/okx_executor.py`; kegagalan eksekusi atau
    notifikasi TIDAK menggagalkan bot sinyal harian.
    """
    if not ENABLE_OKX_AUTOTRADE:
        log.info("Autotrade OKX nonaktif (ENABLE_OKX_AUTOTRADE=false).")
        return

    try:
        from execution.okx_executor import (
            OkxExecutionError,
            build_exchange,
            execute_signal,
        )
        from telegram_sender import (
            notify_execution_failed,
            notify_order_executed,
        )
    except ImportError as exc:
        log.error("Modul autotrade tidak tersedia (%s) - pastikan ccxt terinstall.", exc)
        return

    try:
        exchange = build_exchange()
    except OkxExecutionError as exc:
        log.error("Autotrade tidak siap: %s", exc)
        return

    for signal in signals:
        if signal.action not in (ACTION_BUY, ACTION_SELL):
            continue
        try:
            report = execute_signal(exchange, signal)
            try:
                notify_order_executed(report)
            except TelegramSendError as exc:
                log.warning("Notifikasi ORDER EXECUTED gagal: %s", exc)
        except OkxExecutionError as exc:
            log.error("Eksekusi %s gagal: %s", signal.symbol, exc)
            try:
                notify_execution_failed(signal.symbol, str(exc), signal.action)
            except TelegramSendError as exc2:
                log.warning("Notifikasi EXECUTION FAILED gagal: %s", exc2)


def main() -> int:
    session = current_session()

    try:
        signals, coins = run_scan()
    except Exception as exc:  # noqa: BLE001 - laporkan error apa pun agar terlihat di CI
        log.error("Gagal menjalankan scan: %s", exc)
        return 1

    try:
        evaluation = evaluate_previous_session(coins)
    except Exception as exc:  # noqa: BLE001
        log.warning("Gagal mengevaluasi sesi sebelumnya: %s", exc)
        evaluation = (
            "<b>📊 EVALUASI SINYAL SESI SEBELUMNYA</b>\n🗓️ Gagal memuat data evaluasi."
        )

    timestamp = datetime.now().strftime("%A, %d %b %Y, %H:%M WIB")
    body = format_message(
        signals, timestamp, len(coins), session_label=session_label(session)
    )
    message = evaluation + "\n\n" + body

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Kredensial belum diisi di .env - hasil hanya ditampilkan di konsol.")
        print("\n" + message + "\n")
        run_autotrade(signals)
        return 0

    try:
        send_telegram(message)
        append_signals(signals, session=session)
        log.info("Pesan terkirim ke Telegram & history sinyal (%s) tersimpan.", session)
        run_autotrade(signals)
        return 0
    except TelegramSendError as exc:
        log.error("Gagal mengirim: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
