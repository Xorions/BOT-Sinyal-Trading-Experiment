"""Persistence cooldown sinyal (mode 24/7).

Mencegah spam: koin yang sama (symbol + arah) tidak disinyalkan ulang dalam
rentang `SIGNAL_COOLDOWN_HOURS`. Disimpan di `data/cooldown.json` agar tetap
berlaku walau bot di-restart.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

COOLDOWN_FILE = "data/cooldown.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load() -> Dict[str, str]:
    try:
        with open(COOLDOWN_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: Dict[str, str]) -> None:
    parent = os.path.dirname(COOLDOWN_FILE)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = COOLDOWN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, COOLDOWN_FILE)


def cooldown_key(symbol: str, action: str) -> str:
    return f"{str(symbol).strip().upper()}:{str(action).strip().upper()}"


def last_sent(key: str) -> Optional[datetime]:
    raw = _load().get(key)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def is_blocked(symbol: str, action: str, cooldown_hours: float) -> bool:
    """True bila koin (symbol+arah) masih dalam masa cooldown."""
    if cooldown_hours <= 0:
        return False
    last = last_sent(cooldown_key(symbol, action))
    if last is None:
        return False
    return _now() - last < timedelta(hours=cooldown_hours)


def record_sent(symbol: str, action: str) -> None:
    """Catat waktu sinyal terkirim untuk koin (symbol+arah)."""
    data = _load()
    data[cooldown_key(symbol, action)] = _now().isoformat(timespec="seconds")
    _save(data)