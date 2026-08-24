"""Penyimpanan & evaluasi performa sinyal antar sesi (performance tracking).

Bot berjalan 2x sehari (Sesi Pagi 10:00 WIB dan Sesi Malam 16:00 WIB). Sinyal
yang dikirim disimpan di `data/history.json` dengan kunci (tanggal, sesi).
Setiap sesi HARUS dievaluasi pada sesi berikutnya: sesi Malam mengevaluasi
sinyal sesi Pagi (hari yang sama), sesi Pagi mengevaluasi sinyal sesi Malam
(hari sebelumnya).

Evaluasi membandingkan Entry/SL/TP dengan harga terkini (atau high/low 24j):
HIT TP1, HIT TP2, HIT SL, atau FLOATING. Prioritas hasil: HIT TP2 > HIT TP1 >
HIT SL > FLOATING karena urutan pencapaian level tak bisa diketahui dari
high/low saja.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import (
    EVAL_LOOKBACK_HOURS,
    EVAL_MIN_AGE_HOURS,
    RESULT_LOOKBACK_HOURS,
    SESSION_EVAL_MAX_AGE_DAYS,
    WINRATE_DIGEST_HOUR,
    WINRATE_WINDOW_DAYS,
)
from signals.engine import ACTION_BUY, ACTION_SELL, Signal, signal_levels

HISTORY_FILE = "data/history.json"

SESSION_PAGI = "PAGI"
SESSION_MALAM = "MALAM"
SESSION_SCAN = "SCAN"  # mode 24/7: satu entri per sinyal
SESSION_ORDER = {SESSION_PAGI: 0, SESSION_MALAM: 1}
DEFAULT_SESSION = SESSION_PAGI
WIB_OFFSET = timedelta(hours=7)

RESULT_TP2 = "HIT TP2"
RESULT_TP1 = "HIT TP1"
RESULT_SL = "HIT SL"
RESULT_FLOATING = "FLOATING"

RESULTS_ORDER = (RESULT_TP2, RESULT_TP1, RESULT_SL, RESULT_FLOATING)

# Hasil yang dianggap tuntas (trade selesai).
FINAL_RESULTS = (RESULT_TP2, RESULT_TP1, RESULT_SL)

_RESULT_BADGE = {
    RESULT_TP2: "🎯",
    RESULT_TP1: "✅",
    RESULT_SL: "❌",
}

_SESSION_LABEL = {
    SESSION_PAGI: "Pagi (10:00 WIB)",
    SESSION_MALAM: "Malam (16:00 WIB)",
}


def _now_wib() -> datetime:
    return datetime.now(timezone(WIB_OFFSET))


def current_session() -> str:
    """Sesi saat ini berdasarkan jam lokal WIB (10:00 = PAGI, 16:00 = MALAM)."""
    return SESSION_PAGI if _now_wib().hour < 13 else SESSION_MALAM


def session_label(session: str) -> str:
    return _SESSION_LABEL.get(session, session or DEFAULT_SESSION)


@dataclass
class Eval:
    symbol: str
    action: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    result: str
    price: float


def load_entries() -> List[Dict[str, Any]]:
    """Seluruh entri history yang tersimpan di HISTORY_FILE."""
    return _load_doc().get("entries", [])


def _load_doc() -> Dict[str, Any]:
    """Muat dokumen history utuh (entries + meta)."""
    try:
        with open(HISTORY_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"entries": []}
    if not isinstance(data, dict):
        return {"entries": []}
    entries = data.get("entries", [])
    data["entries"] = entries if isinstance(entries, list) else []
    return data


def _save_doc(doc: Dict[str, Any]) -> None:
    parent = os.path.dirname(HISTORY_FILE)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, HISTORY_FILE)


def _save_entries(entries: List[Dict[str, Any]]) -> None:
    doc = _load_doc()
    doc["entries"] = entries
    _save_doc(doc)


def append_signals(signals: List[Signal], session: Optional[str] = None) -> None:
    """Simpan sinyal BUY/SELL yang dikirim sesi ini ke history.

    Satu kunci (tanggal, sesi) selalu menghasilkan satu evaluasi — entri dengan
    kunci yang sama ditimpa bila bot dijalankan ulang di sesi yang sama.
    """
    session = session or current_session()
    records: List[Dict[str, Any]] = []
    for sig in signals:
        if sig.action not in (ACTION_BUY, ACTION_SELL):
            continue
        sl, tp1, tp2 = signal_levels(sig)
        records.append(
            {
                "coin_id": sig.coin_id,
                "symbol": sig.symbol,
                "name": sig.name,
                "action": sig.action,
                "entry": sig.price,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "confidence": sig.confidence,
            }
        )
    if not records:
        return
    now = _now_wib()
    date = now.strftime("%Y-%m-%d")
    entries = [
        e
        for e in load_entries()
        if not (e.get("date") == date and e.get("session", DEFAULT_SESSION) == session)
    ]
    entries.append(
        {
            "date": date,
            "session": session,
            "saved_at": now.isoformat(timespec="seconds"),
            "signals": records,
        }
    )
    _save_entries(entries)


def _entry_key(entry: Dict[str, Any]) -> tuple:
    return (
        str(entry.get("date", "")),
        SESSION_ORDER.get(entry.get("session", DEFAULT_SESSION), -1),
    )


# ---------------------------------------------------------------------------
# Mode 24/7: satu entri per sinyal (bukan per sesi) + antrian evaluasi
# ---------------------------------------------------------------------------


def _record_from_signal(sig: Signal) -> Dict[str, Any]:
    sl, tp1, tp2 = signal_levels(sig)
    return {
        "coin_id": sig.coin_id,
        "symbol": sig.symbol,
        "name": sig.name,
        "action": sig.action,
        "entry": sig.price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "confidence": sig.confidence,
    }


def append_scan_signal(sig: Signal) -> None:
    """Simpan satu sinyal BUY/SELL sebagai entri independen (mode 24/7).

    Setiap entri punya `key` unik dan dievaluasi satu kali (`evaluated_at`),
    lalu hasilnya dikirim ke group publik.
    """
    now = _now_wib()
    entries = load_entries()
    entries.append(
        {
            "date": now.strftime("%Y-%m-%d"),
            "session": SESSION_SCAN,
            "key": f"{now.strftime('%Y%m%d%H%M%S')}:{sig.coin_id}:{sig.action}",
            "saved_at": now.isoformat(timespec="seconds"),
            "evaluated_at": None,
            "signals": [_record_from_signal(sig)],
        }
    )
    _save_entries(entries)


def load_pending_entries(
    min_age_hours: Optional[float] = None,
    max_age_hours: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Entri sinyal yang menunggu evaluasi (umur antara min & max jam).

    Hanya entri mode SCAN yang belum dievaluasi; sesi PAGI/MALAM lama tidak
    ikut (tetap dievaluasi lewat `load_last_session_entry`).
    """
    min_age = EVAL_MIN_AGE_HOURS if min_age_hours is None else min_age_hours
    max_age = EVAL_LOOKBACK_HOURS if max_age_hours is None else max_age_hours
    now = _now_wib()
    pending: List[Dict[str, Any]] = []
    for entry in load_entries():
        if entry.get("session") != SESSION_SCAN or entry.get("evaluated_at"):
            continue
        saved = entry.get("saved_at")
        if not saved:
            continue
        try:
            saved_ts = datetime.fromisoformat(saved)
        except (TypeError, ValueError):
            continue
        age_hours = (now - saved_ts).total_seconds() / 3600
        if age_hours < min_age or age_hours > max_age:
            continue
        pending.append(entry)
    pending.sort(key=lambda e: str(e.get("saved_at", "")))
    return pending


def mark_entry_evaluated(entry: Dict[str, Any]) -> None:
    """Tandai entri sudah dievaluasi (tidak dikirim ulang ke group publik)."""
    if not entry:
        return
    key = entry.get("key")
    saved_at = entry.get("saved_at")
    entries = load_entries()
    changed = False
    for existing in entries:
        if existing.get("key") == key and existing.get("saved_at") == saved_at:
            existing["evaluated_at"] = _now_wib().isoformat(timespec="seconds")
            changed = True
    if changed:
        _save_entries(entries)


def format_evaluation_pending(
    entries: List[Dict[str, Any]], price_map: Dict[str, Dict[str, float]]
) -> List[str]:
    """Format evaluasi untuk sekumpulan entri 24/7 -> satu pesan per entri."""
    messages: List[str] = []
    for entry in entries:
        date_display = str(entry.get("date", ""))
        try:
            date_display = datetime.strptime(date_display, "%Y-%m-%d").strftime(
                "%d %b %Y"
            )
        except ValueError:
            pass
        saved_at = str(entry.get("saved_at", ""))[11:16] or ""
        evals = evaluate_entry(entry, price_map)
        counts = {result: 0 for result in RESULTS_ORDER}
        for ev in evals:
            counts[ev.result] = counts.get(ev.result, 0) + 1

        lines = [
            "<b>📊 EVALUASI SINYAL (24/7)</b>",
            f"🗓️ {date_display} · {saved_at} WIB",
            (
                f"🎯 HIT TP2: {counts[RESULT_TP2]} · ✅ HIT TP1: {counts[RESULT_TP1]} · "
                f"❌ HIT SL: {counts[RESULT_SL]} · ⏳ FLOATING: {counts[RESULT_FLOATING]}"
            ),
        ]
        if not evals:
            lines.append("Tidak ada sinyal BUY/SELL untuk dievaluasi.")
        else:
            lines.append("━━━━━━━━━━━━")
            for index, ev in enumerate(evals, start=1):
                lines.append(f"{index}. #{ev.symbol} ({ev.action}) → {_result_label(ev)}")
        messages.append("\n".join(lines))
    return messages


def load_last_entry(session: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Entri sesi terakhir yang BUKAN sesi berjalan (untuk dievaluasi)."""
    session = session or current_session()
    today = _now_wib().strftime("%Y-%m-%d")
    candidates = [
        e
        for e in load_entries()
        if not (e.get("date") == today and e.get("session", DEFAULT_SESSION) == session)
    ]
    if not candidates:
        return None
    candidates.sort(key=_entry_key, reverse=True)
    return candidates[0]


def load_last_session_entry(session: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Entri sesi PAGI/MALAM terakhir (legacy, mode non-24/7).

    Entri mode SCAN (24/7) dilewati — evaluasinya ditangani oleh
    `load_pending_entries` supaya tidak terkirim berulang tiap run.
    """
    session = session or current_session()
    today = _now_wib().strftime("%Y-%m-%d")
    candidates = [
        e
        for e in load_entries()
        if e.get("session") in (SESSION_PAGI, SESSION_MALAM)
        and not (
            e.get("date") == today and e.get("session", DEFAULT_SESSION) == session
        )
    ]
    if not candidates:
        return None
    candidates.sort(key=_entry_key, reverse=True)
    return candidates[0]


def _entry_date(entry: Dict[str, Any]) -> Optional[datetime]:
    try:
        naive = datetime.strptime(str(entry.get("date", "")), "%Y-%m-%d")
    except ValueError:
        return None
    return naive.replace(tzinfo=timezone(WIB_OFFSET))


def load_recent_session_entries(
    max_age_days: Optional[int] = None,
    session: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Entri sesi PAGI/MALAM dalam jendela umur (urut lama -> terbaru).

    Dipakai evaluasi legacy (`evaluate_previous_session`): entri mode SCAN
    (24/7) dilewati, entri sesi berjalan hari ini dikecualikan, dan entri
    lebih tua dari `max_age_days` tidak layak ditampilkan ulang.
    """
    max_age = SESSION_EVAL_MAX_AGE_DAYS if max_age_days is None else max_age_days
    session = session or current_session()
    now = now or _now_wib()
    today = now.strftime("%Y-%m-%d")
    out: List[Dict[str, Any]] = []
    for entry in load_entries():
        if entry.get("session") not in (SESSION_PAGI, SESSION_MALAM):
            continue
        if entry.get("date") == today and entry.get("session", DEFAULT_SESSION) == session:
            continue
        entry_dt = _entry_date(entry)
        if entry_dt is None or (now - entry_dt) >= timedelta(days=max_age):
            continue
        out.append(entry)
    out.sort(key=_entry_key)
    return out


def _evaluate_one(record: Dict[str, Any], price_info: Dict[str, float]) -> Eval:
    symbol = str(record.get("symbol", "?"))
    action = str(record.get("action", ACTION_BUY))
    entry = float(record.get("entry") or 0)
    sl = float(record.get("sl") or 0)
    tp1 = float(record.get("tp1") or 0)
    tp2 = float(record.get("tp2") or 0)
    current = float((price_info or {}).get("current_price") or 0)

    if current <= 0 or entry <= 0:
        return Eval(symbol, action, entry, sl, tp1, tp2, RESULT_FLOATING, current)

    high = float((price_info or {}).get("high_24h") or 0) or current
    low = float((price_info or {}).get("low_24h") or 0) or current

    if action == ACTION_SELL:
        if low <= tp2:
            result = RESULT_TP2
        elif low <= tp1:
            result = RESULT_TP1
        elif high >= sl:
            result = RESULT_SL
        else:
            result = RESULT_FLOATING
    else:
        if high >= tp2:
            result = RESULT_TP2
        elif high >= tp1:
            result = RESULT_TP1
        elif low <= sl:
            result = RESULT_SL
        else:
            result = RESULT_FLOATING
    return Eval(symbol, action, entry, sl, tp1, tp2, result, current)


def evaluate_entry(
    entry: Optional[Dict[str, Any]], price_map: Dict[str, Dict[str, float]]
) -> List[Eval]:
    """Evaluasi semua sinyal pada `entry` dengan peta harga terkini."""
    if not entry:
        return []
    evals: List[Eval] = []
    for record in entry.get("signals", []):
        info = price_map.get(str(record.get("coin_id", "")), {})
        evals.append(_evaluate_one(record, info))
    return evals


def _result_label(ev: Eval) -> str:
    if ev.result == RESULT_FLOATING:
        if ev.price <= 0:
            return "⏳ FLOATING (no data)"
        pct = (ev.price - ev.entry) / ev.entry * 100
        return f"⏳ FLOATING ({pct:+.1f}%)"
    level = {
        RESULT_TP2: ev.tp2,
        RESULT_TP1: ev.tp1,
        RESULT_SL: ev.sl,
    }[ev.result]
    pct = (level - ev.entry) / ev.entry * 100
    return f"{_RESULT_BADGE[ev.result]} {ev.result} ({pct:+.1f}%)"


def format_evaluation(
    entry: Optional[Dict[str, Any]], price_map: Dict[str, Dict[str, float]]
) -> str:
    """Ringkasan evaluasi sinyal sesi sebelumnya, diletakkan di atas pesan."""
    if not entry:
        return "<b>📊 EVALUASI SINYAL SESI SEBELUMNYA</b>\n🗓️ Belum ada data sesi sebelumnya."

    date_display = str(entry.get("date", ""))
    try:
        date_display = datetime.strptime(date_display, "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        pass

    prev_session = str(entry.get("session", DEFAULT_SESSION))
    evals = evaluate_entry(entry, price_map)
    counts = {result: 0 for result in RESULTS_ORDER}
    for ev in evals:
        counts[ev.result] = counts.get(ev.result, 0) + 1

    lines = [
        "<b>📊 EVALUASI SINYAL SESI SEBELUMNYA</b>",
        f"🗓️ {date_display} · Sesi {session_label(prev_session)}",
        (
            f"🎯 HIT TP2: {counts[RESULT_TP2]} · ✅ HIT TP1: {counts[RESULT_TP1]} · "
            f"❌ HIT SL: {counts[RESULT_SL]} · ⏳ FLOATING: {counts[RESULT_FLOATING]}"
        ),
    ]
    if not evals:
        lines.append("Tidak ada sinyal BUY/SELL untuk dievaluasi.")
        return "\n".join(lines)

    lines.append("━━━━━━━━━━━━")
    for index, ev in enumerate(evals, start=1):
        lines.append(f"{index}. #{ev.symbol} ({ev.action}) → {_result_label(ev)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pencatatan hasil (win-rate): hasil final terkunci, FLOATING boleh naik
# ---------------------------------------------------------------------------


def _stored_result(record: Dict[str, Any]) -> str:
    return str(record.get("result") or "")


def _result_rank(result: str) -> int:
    """Semakin kecil semakin baik (TP2 > TP1 > SL > FLOATING > kosong)."""
    try:
        return RESULTS_ORDER.index(result)
    except ValueError:
        return len(RESULTS_ORDER)


_FINAL_RESULTS_SET = set(FINAL_RESULTS)


def _apply_results(entry: Dict[str, Any], evals: List[Eval]) -> bool:
    """Terapkan hasil evaluasi ke record sinyal (hanya upgrade, tak pernah turun).

    Hasil final (TP1/TP2/SL) terkunci; FLOATING boleh ditingkatkan pada
    pengecekan berikutnya. Return True bila ada perubahan.
    """
    changed = False
    for record, ev in zip(entry.get("signals", []), evals):
        previous = _stored_result(record)
        if previous in _FINAL_RESULTS_SET:
            continue  # sudah final — terkunci
        if _result_rank(ev.result) < _result_rank(previous):
            record["result"] = ev.result
            record["result_price"] = ev.price
            record["result_at"] = _now_wib().isoformat(timespec="seconds")
            changed = True
    return changed


def _entry_saved_dt(entry: Dict[str, Any]) -> Optional[datetime]:
    """Waktu tersimpan entri (dari saved_at, fallback tanggal) dalam tz WIB."""
    saved = str(entry.get("saved_at") or "")
    try:
        ts = datetime.fromisoformat(saved)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone(WIB_OFFSET))
        return ts
    except (TypeError, ValueError):
        return _entry_date(entry)


def update_results(
    price_map: Dict[str, Dict[str, float]],
    max_age_hours: Optional[float] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Cek ulang SEMUA sinyal belum tuntas dalam jendela umur & simpan hasil.

    Dipanggil tiap siklus scan: sinyal masih mengambang terus dicek sampai
    kena TP1/TP2/SL (terkunci) atau lewat `RESULT_LOOKBACK_HOURS`. Return
    True bila ada hasil baru yang tersimpan.
    """
    cutoff = RESULT_LOOKBACK_HOURS if max_age_hours is None else max_age_hours
    now = now or _now_wib()
    entries = load_entries()
    changed = False
    for entry in entries:
        ts = _entry_saved_dt(entry)
        if ts is None or (now - ts).total_seconds() / 3600 > cutoff:
            continue
        if all(_stored_result(r) in set(FINAL_RESULTS) for r in entry.get("signals", [])):
            continue
        if _apply_results(entry, evaluate_entry(entry, price_map)):
            changed = True
    if changed:
        _save_entries(entries)
    return changed


def _trade_r_multiple(record: Dict[str, Any], result: str) -> float:
    """Hasil trade dalam satuan R (risiko = |entry − SL|).

    TP1 → full TP1. TP2 → 50% TP1 + 50% TP2 (mencerminkan exit executor).
    SL → -1R. Nilai tak valid → 0.0 (netral).
    """
    try:
        entry = float(record.get("entry") or 0)
        sl = float(record.get("sl") or 0)
        tp1 = float(record.get("tp1") or 0)
        tp2 = float(record.get("tp2") or 0)
        action = str(record.get("action") or ACTION_BUY)
    except (TypeError, ValueError):
        return 0.0
    risk = abs(entry - sl)
    if risk <= 0 or entry <= 0:
        return 0.0
    sign = -1.0 if action == ACTION_SELL else 1.0

    def _level_r(level: float) -> Optional[float]:
        return sign * (level - entry) / risk if level > 0 else None

    if result == RESULT_SL:
        return -1.0
    if result == RESULT_TP1:
        return _level_r(tp1) or 0.0
    if result == RESULT_TP2:
        r_tp1, r_tp2 = _level_r(tp1), _level_r(tp2)
        if r_tp1 is None and r_tp2 is None:
            return 0.0
        if r_tp1 is None:
            return r_tp2 or 0.0
        if r_tp2 is None:
            return r_tp1
        return 0.5 * r_tp1 + 0.5 * r_tp2
    return 0.0


def winrate_stats(
    entries: Optional[List[Dict[str, Any]]] = None,
    days: Optional[int] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Statistik performa sinyal dalam jendela `days` hari terakhir."""
    window = WINRATE_WINDOW_DAYS if days is None else days
    now = now or _now_wib()
    cutoff = now - timedelta(days=window)
    counts = {RESULT_TP2: 0, RESULT_TP1: 0, RESULT_SL: 0}
    total = closed = floating = 0
    r_sum = 0.0
    dates: List[str] = []
    for entry in load_entries() if entries is None else entries:
        entry_dt = _entry_date(entry)
        if entry_dt is None or entry_dt < cutoff:
            continue
        dates.append(str(entry.get("date", "")))
        for record in entry.get("signals", []):
            total += 1
            result = _stored_result(record)
            if result in counts:
                counts[result] += 1
                closed += 1
                r_sum += _trade_r_multiple(record, result)
            elif not result or result == RESULT_FLOATING:
                floating += 1
    wins = counts[RESULT_TP1] + counts[RESULT_TP2]
    return {
        "days": window,
        "total": total,
        "closed": closed,
        "floating": floating,
        "tp2": counts[RESULT_TP2],
        "tp1": counts[RESULT_TP1],
        "sl": counts[RESULT_SL],
        "win_rate": (wins / closed * 100.0) if closed else None,
        "expectancy": (r_sum / closed) if closed else None,
        "first_date": min(dates) if dates else "",
        "last_date": max(dates) if dates else "",
    }


def format_winrate_summary(
    days: Optional[int] = None,
    entries: Optional[List[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> str:
    """Ringkasan win-rate kumulatif untuk digest harian grup evaluasi."""
    stats = winrate_stats(entries=entries, days=days, now=now)
    window = stats["days"]
    header = f"<b>📈 PERFORMA SINYAL {window} HARI TERAKHIR</b>"
    if stats["total"] == 0:
        return f"{header}\n🗓️ Belum ada sinyal dalam {window} hari terakhir."

    lines = [header]
    try:
        first = datetime.strptime(stats["first_date"], "%Y-%m-%d").strftime("%d %b")
        last = datetime.strptime(stats["last_date"], "%Y-%m-%d").strftime("%d %b %Y")
        if first and last:
            lines.insert(1, f"🗓️ {first} – {last}")
    except ValueError:
        pass

    lines.append(
        f"Sinyal: {stats['total']} · Tuntas: {stats['closed']} · "
        f"⏳ Mengambang: {stats['floating']}"
    )
    lines.append(
        f"🎯 TP2: {stats['tp2']} · ✅ TP1: {stats['tp1']} · ❌ SL: {stats['sl']}"
    )

    if stats["win_rate"] is None:
        verdict = "⏳ Belum ada sinyal tuntas untuk menghitung win rate."
    else:
        verdict = (
            f"✅ Win rate: {stats['win_rate']:.0f}% ({stats['tp1'] + stats['tp2']}"
            f"/{stats['closed']} tuntas)"
        )
        if stats["expectancy"] is not None:
            verdict += f" · 📊 Ekspektasi: {stats['expectancy']:+.2f}R/trade"
    lines.append(verdict)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Digest win-rate harian (sekali per hari WIB, state tersimpan di meta)
# ---------------------------------------------------------------------------


def should_send_winrate_digest(
    min_hour: Optional[int] = None, now: Optional[datetime] = None
) -> bool:
    """True bila digest win-rate hari ini belum terkirim dan sudah lewat jamnya."""
    hour_min = WINRATE_DIGEST_HOUR if min_hour is None else min_hour
    now = now or _now_wib()
    doc = _load_doc()
    sent = str((doc.get("meta") or {}).get("winrate_digest_sent", ""))
    return now.strftime("%Y-%m-%d") != sent and now.hour >= hour_min


def mark_winrate_digest_sent(now: Optional[datetime] = None) -> None:
    now = now or _now_wib()
    doc = _load_doc()
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    meta["winrate_digest_sent"] = now.strftime("%Y-%m-%d")
    meta["winrate_digest_at"] = now.isoformat(timespec="seconds")
    doc["meta"] = meta
    _save_doc(doc)
