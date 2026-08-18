"""Mengirim pesan & foto ke Telegram via Bot API (HTTP langsung, tanpa library besar)."""

import logging

import requests

from config import (
    REQUEST_TIMEOUT,
    TELEGRAM_ADMIN_CHAT_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_EVAL_CHAT_ID,
    TELEGRAM_SIGNAL_CHAT_ID,
)

log = logging.getLogger("signal-bot.telegram")

TELEGRAM_API = "https://api.telegram.org"
# Batas caption foto di Telegram Bot API (karakter).
PHOTO_CAPTION_MAX = 1024


class TelegramSendError(Exception):
    """Gagal mengirim pesan ke Telegram."""


def signal_chat_id() -> str:
    """Chat private untuk sinyal (fallback TELEGRAM_CHAT_ID)."""
    return (TELEGRAM_SIGNAL_CHAT_ID or TELEGRAM_CHAT_ID).strip()


def eval_chat_id() -> str:
    """Group publik untuk hasil evaluasi (fallback TELEGRAM_CHAT_ID)."""
    return (TELEGRAM_EVAL_CHAT_ID or TELEGRAM_CHAT_ID).strip()


def _api_url(token: str, method: str) -> str:
    return f"{TELEGRAM_API}/bot{token}/{method}"


def _post(payload: dict, method: str) -> None:
    token = TELEGRAM_BOT_TOKEN.strip()
    if not token:
        raise TelegramSendError("TELEGRAM_BOT_TOKEN belum diisi di .env")
    resp = requests.post(_api_url(token, method), json=payload, timeout=REQUEST_TIMEOUT)
    if resp.status_code != 200:
        raise TelegramSendError(f"Telegram API error {resp.status_code}: {resp.text[:200]}")


def _truncate_caption(text: str) -> str:
    """Potong caption ke maksimum Telegram tanpa menyisakan tag HTML terputus."""
    if len(text) <= PHOTO_CAPTION_MAX:
        return text
    cut = text[:PHOTO_CAPTION_MAX]
    last_tag = cut.rfind("<")
    last_gt = cut.rfind(">")
    if last_tag > last_gt:
        cut = cut[:last_tag]
    return cut


def _send_message(text: str, chat: str) -> None:
    payload = {
        "chat_id": chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    _post(payload, "sendMessage")


def _send_photo(image_url: str, caption: str, chat: str) -> None:
    payload = {
        "chat_id": chat,
        "photo": image_url,
        "caption": _truncate_caption(caption),
        "parse_mode": "HTML",
    }
    _post(payload, "sendPhoto")


def send_telegram_photo(image_url: str, caption: str, chat_id: str = "") -> None:
    """Kirim foto via endpoint sendPhoto (caption dibatasi 1024 karakter)."""
    chat = (chat_id or TELEGRAM_CHAT_ID).strip()
    if not chat:
        raise TelegramSendError("TELEGRAM_CHAT_ID belum diisi di .env")
    _send_photo(image_url, caption, chat)


def send_telegram(text: str, chat_id: str = "", image_url: str = "") -> None:
    """Kirim notifikasi ke Telegram.

    Bila `image_url` diisi, kirim via endpoint sendPhoto dengan teks sinyal
    sebagai caption (maks 1024 karakter; bila teks lebih panjang, caption
    dipotong rapi dan teks lengkap tetap dikirim via sendMessage setelahnya).
    Bila pengiriman foto gagal, fallback ke sendMessage teks penuh agar
    sinyal tidak pernah hilang. Tanpa `image_url`, perilaku lama: sendMessage.
    """
    chat = (chat_id or TELEGRAM_CHAT_ID).strip()
    if not chat:
        raise TelegramSendError("TELEGRAM_CHAT_ID belum diisi di .env")

    if not image_url:
        _send_message(text, chat)
        return

    try:
        send_telegram_photo(image_url, text, chat_id=chat)
    except TelegramSendError as exc:
        log.warning("sendPhoto gagal (%s) — fallback ke sendMessage teks penuh.", exc)
        _send_message(text, chat)
        return

    if len(text) > PHOTO_CAPTION_MAX:
        _send_message(text, chat)


# ---------------------------------------------------------------------------
# Laporan private eksekusi trading (Bybit Futures) ke TELEGRAM_ADMIN_CHAT_ID
# ---------------------------------------------------------------------------


def _admin_chat_id() -> str:
    chat = TELEGRAM_ADMIN_CHAT_ID.strip()
    if not chat:
        raise TelegramSendError(
            "TELEGRAM_ADMIN_CHAT_ID belum diisi di .env — laporan eksekusi tidak dikirim."
        )
    return chat


def _fmt_usd(value: float) -> str:
    try:
        if value >= 1000:
            return f"${value:,.2f}"
        return f"${value:,.4f}"
    except (TypeError, ValueError):
        return "-"


def _fmt_price(value: float) -> str:
    try:
        if value >= 1000:
            return f"${value:,.2f}"
        if value >= 1:
            return f"${value:,.4f}"
        return f"${value:.8f}"
    except (TypeError, ValueError):
        return "-"


def notify_order_executed(report: dict) -> None:
    """🚀 [ORDER EXECUTED] — order berhasil dipasang di Bybit (ke admin)."""
    lines = [
        "🚀 <b>[ORDER EXECUTED]</b>",
        f"💱 #{report.get('symbol')} <b>{report.get('action')}</b> · Bybit Futures (USDT-M)",
        f"🔑 Entry: <b>{_fmt_price(report.get('entry'))}</b>",
        f"🪓 SL: {_fmt_price(report.get('sl'))} (full position)",
        f"💰 TP1 (50%): {_fmt_price(report.get('tp1'))}",
        f"💰 TP2 (50%): {_fmt_price(report.get('tp2'))}",
        f"📦 Size: {report.get('amount_contracts')} kontrak "
        f"({report.get('amount_coins'):.6g} {report.get('symbol')})",
        f"⚖️ Risiko: {_fmt_usd(report.get('risk_usd'))} "
        f"dari saldo {_fmt_usd(report.get('free_balance'))}",
        f"🧾 Order ID: <code>{report.get('order_id')}</code>",
        f"🎯 TP1 ID: <code>{report.get('tp1_order_id')}</code> · "
        f"TP2 ID: <code>{report.get('tp2_order_id')}</code>",
    ]
    send_telegram("\n".join(lines), chat_id=_admin_chat_id())


def notify_execution_failed(symbol: str, reason: str, action: str = "") -> None:
    """⚠️ [EXECUTION FAILED] — saldo tidak cukup / API error (ke admin)."""
    lines = [
        "⚠️ <b>[EXECUTION FAILED]</b>",
        f"💱 #{symbol}" + (f" <b>{action}</b>" if action else ""),
        f"❌ Tidak ada order yang dipasang.",
        f"📛 Alasan: {reason}",
    ]
    send_telegram("\n".join(lines), chat_id=_admin_chat_id())
