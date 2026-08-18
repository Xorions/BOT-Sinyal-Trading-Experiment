"""Entry point bot sinyal trading 24/7 (scan non-stop).

Alur per siklus scan:
1. Quick scan top koin (satu panggilan CoinGecko) untuk shortlist kandidat.
2. Deep scan Multi-Timeframe (MTF) untuk kandidat: HTF 4H/1D (trend bias) +
   LTF 1H/15M (entry/SL/TP) + konfluensi SMC, S&D/S&R, MACD/RSI, Whale/Volume.
3. Pilih HANYA 1 koin terbaik (BUY/SELL) — dikirim ke chat PRIVATE hanya bila
   confidence >= SIGNAL_MIN_CONFIDENCE (default 65%), dengan gambar chart.
   Koin yang sama (symbol+arah) tidak dikirim ulang dalam masa cooldown.
4. Evaluasi sinyal sebelumnya (umur >= EVAL_MIN_AGE_HOURS) dikirim ke GROUP
   PUBLIK, juga dengan gambar chart per sinyal.
5. Autotrade Bybit tetap opsional & default nonaktif (ENABLE_BYBIT_AUTOTRADE=false).

Mode:
- `python bot.py`            : satu siklus scan (untuk tes / CI).
- `python bot.py --loop`     : scan 24/7 non-stop dengan jeda SCAN_INTERVAL_MINUTES.
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from typing import List, Optional

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (ValueError, OSError):
        pass

from config import (
    ENABLE_BYBIT_AUTOTRADE,
    SCAN_INTERVAL_MINUTES,
    SIGNAL_COOLDOWN_HOURS,
    SIGNAL_MIN_CONFIDENCE,
    TELEGRAM_BOT_TOKEN,
    TOP_COINS,
)
from data.cooldown import is_blocked, record_sent
from data.history import (
    append_scan_signal,
    current_session,
    format_evaluation,
    format_evaluation_pending,
    load_last_session_entry,
    load_pending_entries,
    mark_entry_evaluated,
    session_label,
)
from data.market import coin_price_map, get_prices_for_ids, get_top_coins
from signals.engine import ACTION_BUY, ACTION_SELL, Signal, format_message, rank_signals
from telegram_sender import (
    TelegramSendError,
    eval_chat_id,
    send_telegram,
    signal_chat_id,
)

from execution.chart_visualizer import generate_chart_url

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
            "Sinyal %s -> %s (skor %+.1f) | confidence %d%% | HTF %s | %s",
            sig.symbol,
            sig.action,
            sig.score,
            sig.confidence,
            sig.ht_bias or "-",
            " | ".join(f"{k}:{a}/{t}" for k, (a, t) in sig.checklist.items()) or "no-MTF",
        )
    return signals, coins


def pick_best_signal(signals: List[Signal]) -> Optional[Signal]:
    """Koin BUY/SELL terbaik dari hasil scan (hanya 1)."""
    candidates = [s for s in signals if s.action in (ACTION_BUY, ACTION_SELL)]
    if not candidates:
        return None
    return max(candidates, key=lambda s: abs(s.score))


def chart_url_for_signal(sig: Signal, timeframe: str = "") -> str:
    """URL gambar chart TradingView untuk sinyal (kosong bila gagal)."""
    return (
        generate_chart_url(
            sig.symbol,
            sig.action,
            sig.price,
            sig.sl,
            sig.tp1,
            sig.tp2,
            timeframe=timeframe or sig.ltf,
        )
        or ""
    )


def send_best_signal(signals: List[Signal], total_scanned: int, session: str) -> bool:
    """Kirim 1 koin terbaik ke chat PRIVATE (confidence >= 65%, cek cooldown).

    Returns True bila sinyal terkirim (history & cooldown dicatat).
    """
    best = pick_best_signal(signals)
    if best is None:
        log.info("Tidak ada koin BUY/SELL pada scan ini — tidak mengirim sinyal.")
        return False
    if best.confidence < SIGNAL_MIN_CONFIDENCE:
        log.info(
            "#%s confidence %d%% < %d%% — tidak memenuhi syarat, tidak dikirim.",
            best.symbol,
            best.confidence,
            SIGNAL_MIN_CONFIDENCE,
        )
        return False
    if is_blocked(best.symbol, best.action, SIGNAL_COOLDOWN_HOURS):
        log.info(
            "#%s %s masih dalam cooldown — dilewati.",
            best.symbol,
            best.action,
        )
        return False

    timestamp = datetime.now().strftime("%A, %d %b %Y, %H:%M WIB")
    message = format_message(
        [best],
        timestamp,
        total_scanned,
        session_label=f"Sinyal #{best.symbol} · Sesi {session_label(session)}",
    )
    image_url = chart_url_for_signal(best)

    if not TELEGRAM_BOT_TOKEN or not signal_chat_id():
        log.warning("Kredensial belum diisi di .env - hasil hanya ditampilkan di konsol.")
        print("\n" + message + "\n")
        return False

    try:
        send_telegram(message, chat_id=signal_chat_id(), image_url=image_url)
        append_scan_signal(best)
        record_sent(best.symbol, best.action)
        log.info(
            "Sinyal #%s (%s, confidence %d%%) terkirim ke chat private & tersimpan.",
            best.symbol,
            best.action,
            best.confidence,
        )
        return True
    except TelegramSendError as exc:
        log.error("Gagal mengirim sinyal: %s", exc)
        return False


def send_pending_evaluations(coins: list) -> None:
    """Kirim hasil evaluasi sinyal 24/7 ke group PUBLIK (dengan gambar chart)."""
    pending = load_pending_entries()
    if not pending:
        return
    if not TELEGRAM_BOT_TOKEN or not eval_chat_id():
        log.warning("Kredensial evaluasi belum diisi di .env - evaluasi dilewati.")
        return

    coin_ids = sorted(
        {
            record.get("coin_id")
            for entry in pending
            for record in entry.get("signals", [])
            if record.get("coin_id")
        }
    )
    price_map = coin_price_map(coins)
    missing = [cid for cid in coin_ids if cid not in price_map]
    if missing:
        try:
            price_map.update(get_prices_for_ids(missing))
        except Exception as exc:  # noqa: BLE001 - evaluasi tidak menggagalkan scan
            log.warning("Gagal mengambil harga untuk evaluasi: %s", exc)

    messages = format_evaluation_pending(pending, price_map)
    for entry, message in zip(pending, messages):
        try:
            record = (entry.get("signals") or [{}])[0]
            image_url = ""
            try:
                image_url = (
                    generate_chart_url(
                        record.get("symbol", ""),
                        record.get("action", ACTION_BUY),
                        float(record.get("entry") or 0),
                        float(record.get("sl") or 0),
                        float(record.get("tp1") or 0),
                        float(record.get("tp2") or 0),
                        timeframe="1h",
                    )
                    or ""
                )
            except (TypeError, ValueError):
                image_url = ""
            send_telegram(message, chat_id=eval_chat_id(), image_url=image_url)
            mark_entry_evaluated(entry)
            log.info(
                "Evaluasi #%s terkirim ke group publik.",
                (record.get("symbol") or "?"),
            )
        except TelegramSendError as exc:
            log.error("Gagal mengirim evaluasi: %s", exc)
            return


def evaluate_previous_session(coins: list) -> str:
    """Evaluasi sinyal sesi sebelumnya dengan harga saat ini (mode non-24/7)."""
    prev_entry = load_last_session_entry()
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


def send_previous_session_evaluation(coins: list) -> None:
    """Kirim evaluasi sesi PAGI/MALAM sebelumnya ke group publik (mode non-24/7).

    Dipakai saat `python bot.py` / GitHub Actions (daily.yml). Evaluasi 24/7
    ditangani terpisah oleh `send_pending_evaluations`.
    """
    if not TELEGRAM_BOT_TOKEN or not eval_chat_id():
        return
    try:
        evaluation = evaluate_previous_session(coins)
    except Exception as exc:  # noqa: BLE001
        log.warning("Gagal mengevaluasi sesi sebelumnya: %s", exc)
        evaluation = (
            "<b>📊 EVALUASI SINYAL SESI SEBELUMNYA</b>\n🗓️ Gagal memuat data evaluasi."
        )

    image_url = ""
    prev_entry = load_last_session_entry()
    if prev_entry:
        record = (prev_entry.get("signals") or [{}])[0]
        try:
            image_url = (
                generate_chart_url(
                    record.get("symbol", ""),
                    record.get("action", ACTION_BUY),
                    float(record.get("entry") or 0),
                    float(record.get("sl") or 0),
                    float(record.get("tp1") or 0),
                    float(record.get("tp2") or 0),
                    timeframe="1h",
                )
                or ""
            )
        except (TypeError, ValueError):
            image_url = ""
    try:
        send_telegram(evaluation, chat_id=eval_chat_id(), image_url=image_url)
        log.info("Evaluasi sesi sebelumnya terkirim ke group publik.")
    except TelegramSendError as exc:
        log.error("Gagal mengirim evaluasi sesi sebelumnya: %s", exc)


def run_autotrade(signals: list) -> None:
    """Eksekusi sinyal BUY/SELL valid ke Bybit Futures (hanya jika diaktifkan).

    Modul terpisah `execution/bybit_executor.py`; kegagalan eksekusi atau
    notifikasi TIDAK menggagalkan bot sinyal.
    """
    if not ENABLE_BYBIT_AUTOTRADE:
        log.info("Autotrade Bybit nonaktif (ENABLE_BYBIT_AUTOTRADE=false).")
        return

    try:
        from execution.bybit_executor import (
            BybitExecutionError,
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
    except BybitExecutionError as exc:
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
        except BybitExecutionError as exc:
            log.error("Eksekusi %s gagal: %s", signal.symbol, exc)
            try:
                notify_execution_failed(signal.symbol, str(exc), signal.action)
            except TelegramSendError as exc2:
                log.warning("Notifikasi EXECUTION FAILED gagal: %s", exc2)


def run_one_cycle(legacy_eval: bool = False) -> None:
    """Satu siklus: scan -> kirim sinyal private -> evaluasi ke public -> autotrade."""
    session = current_session()

    try:
        signals, coins = run_scan()
    except Exception as exc:  # noqa: BLE001 - laporkan error apa pun agar terlihat di CI
        log.error("Gagal menjalankan scan: %s", exc)
        return

    try:
        send_pending_evaluations(coins)
    except Exception as exc:  # noqa: BLE001
        log.error("Gagal mengirim evaluasi 24/7: %s", exc)

    if legacy_eval:
        try:
            send_previous_session_evaluation(coins)
        except Exception as exc:  # noqa: BLE001
            log.error("Gagal mengirim evaluasi sesi sebelumnya: %s", exc)

    try:
        send_best_signal(signals, len(coins), session)
    except Exception as exc:  # noqa: BLE001
        log.error("Gagal mengirim sinyal terbaik: %s", exc)

    try:
        run_autotrade(signals)
    except Exception as exc:  # noqa: BLE001
        log.error("Autotrade gagal: %s", exc)


def run_loop(interval_minutes: float) -> None:
    """Scan 24/7 non-stop dengan jeda `interval_minutes` menit per siklus."""
    log.info(
        "Mode 24/7 aktif: scan tiap %.1f menit (cooldown sinyal & evaluasi aktif).",
        interval_minutes,
    )
    log.info(
        "Hanya mengirim 1 koin terbaik dengan confidence >= %d%% ke chat private, "
        "hasil evaluasi ke group publik.",
        SIGNAL_MIN_CONFIDENCE,
    )
    interval_seconds = max(60.0, interval_minutes * 60.0)
    while True:
        started = time.time()
        try:
            run_one_cycle()
        except Exception as exc:  # noqa: BLE001 - bot tidak boleh mati karena error per siklus
            log.error("Error pada siklus: %s", exc)
        elapsed = time.time() - started
        log.info("Siklus selesai dalam %.1fs — tidur %.1f menit.", elapsed, interval_minutes)
        time.sleep(interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bot sinyal trading 24/7")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Scan 24/7 non-stop (default: satu siklus saja).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Jeda antar scan dalam menit (default SCAN_INTERVAL_MINUTES dari .env).",
    )
    args = parser.parse_args()

    if args.loop:
        run_loop(args.interval if args.interval is not None else SCAN_INTERVAL_MINUTES)
        return 0

    run_one_cycle(legacy_eval=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
