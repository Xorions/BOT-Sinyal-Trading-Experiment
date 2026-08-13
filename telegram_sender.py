"""Mengirim pesan ke Telegram via Bot API (HTTP langsung, tanpa library besar)."""

import requests

from config import (
    REQUEST_TIMEOUT,
    TELEGRAM_ADMIN_CHAT_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)


class TelegramSendError(Exception):
    """Gagal mengirim pesan ke Telegram."""


def send_telegram(text: str, chat_id: str = "") -> None:
    token = TELEGRAM_BOT_TOKEN.strip()
    chat = (chat_id or TELEGRAM_CHAT_ID).strip()
    if not token or not chat:
        raise TelegramSendError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID belum diisi di .env")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    if resp.status_code != 200:
        raise TelegramSendError(f"Telegram API error {resp.status_code}: {resp.text[:200]}")


# ---------------------------------------------------------------------------
# Laporan private eksekusi trading (Bitget Futures) ke TELEGRAM_ADMIN_CHAT_ID
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
    """🚀 [ORDER EXECUTED] — order berhasil dipasang di Bitget (ke admin)."""
    lines = [
        "🚀 <b>[ORDER EXECUTED]</b>",
        f"💱 #{report.get('symbol')} <b>{report.get('action')}</b> · Bitget Futures (USDT-M)",
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
