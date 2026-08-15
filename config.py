"""Konfigurasi bot: memuat kredensial dari file .env"""

import os
from dotenv import load_dotenv

load_dotenv()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
# Chat ID khusus admin untuk laporan private eksekusi order Bybit
# (tidak meneruskan ke TELEGRAM_CHAT_ID publik).
TELEGRAM_ADMIN_CHAT_ID: str = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")

TOP_COINS: int = _env_int("TOP_COINS", 250)
TOP_SIGNALS: int = _env_int("TOP_SIGNALS", 5)

# Day Trading Lanjutan — Analisis Multi-Timeframe (MTF)
# Jumlah kandidat yang dianalisis mendalam (ambil chart 2x per koin dari CoinGecko).
MTF_SCAN_LIMIT: int = _env_int("MTF_SCAN_LIMIT", 6)
# Minimal kategori Confluence yang harus selaras sebelum sinyal dipromosikan
# dari NEUTRAL menjadi BUY/SELL (kategori: SMC/OB, S&D/S&R, MACD/RSI, Whale/Vol).
CONFLUENCE_MIN: int = _env_int("CONFLUENCE_MIN", 2)
# Minimal cek selaras WAJIB dari kategori inti (S&D/S&R + MACD/RSI) agar sinyal
# BUY/SELL valid. 0 = nonaktif (perilaku lama). Mencegah sinyal yang hanya
# bermodal SMC/OB (contoh: SMC/OB 2/2, tapi S&D/S&R 0/2 & MACD/RSI 0/2) lolos —
# penting ganda bila autotrade Bybit diaktifkan.
REQUIRE_CONFLUENCE_CORE: int = _env_int("REQUIRE_CONFLUENCE_CORE", 1)
# SL/TP berbasis ATR (timeframe 1H). TP1 = 2x ATR, TP2 = 3x ATR.
# ATR_SL_MULT dinaikkan dari 1.5x ke 2.0x karena 1.5x ATR terlalu rapat di
# kondisi volatilitas tinggi (sering kena wick -> HIT SL sebelum arah terbentuk).
ATR_SL_MULT: float = _env_float("ATR_SL_MULT", 2.0)
ATR_TP1_MULT: float = _env_float("ATR_TP1_MULT", 2.0)
ATR_TP2_MULT: float = _env_float("ATR_TP2_MULT", 3.0)
# SL juga dipasang di luar Key Level terdekat (swing low/high) bila lebih aman:
# buffer di luar level (dalam satuan ATR) dan lebar maksimal SL (dalam ATR)
# agar risk-reward tidak rusak (SL terlalu jauh dari entry).
SWING_SL_BUFFER_MULT: float = _env_float("SWING_SL_BUFFER_MULT", 0.5)
MAX_SL_MULT: float = _env_float("MAX_SL_MULT", 2.5)
# Ambang deteksi Whale Spike (volume 1H vs rata-rata 20 bar sebelumnya).
WHALE_VOLUME_MULT: float = _env_float("WHALE_VOLUME_MULT", 2.5)

# Opsional: free API key dari CoinGecko (https://www.coingecko.com/en/api)
# Tanpa key pakai kuota publik kecil, dengan key 30 req/menit.
COINGECKO_API_KEY: str = os.getenv("COINGECKO_API_KEY", "")
BUY_THRESHOLD: float = _env_float("BUY_THRESHOLD", 3.0)
SELL_THRESHOLD: float = _env_float("SELL_THRESHOLD", -3.0)

# --- Automated Trading Bybit Futures (opsional, default NONAKTIF) ---
# Buat API key di Bybit: https://www.bybit.com/app/user/api-management →
# buat key (Unified Trading Account) → aktifkan izin "Order" (trade) saja.
# Bybit API v5 hanya butuh API Key + Secret (TIDAK ada passphrase).
# Simpan keduanya di .env, TIDAK pernah di-hardcode.
BYBIT_API_KEY: str = os.getenv("BYBIT_API_KEY", "")
BYBIT_SECRET_KEY: str = os.getenv("BYBIT_SECRET_KEY", "")
# Sakelar utama autotrade: "true" mengeksekusi order NYATA di Bybit Futures.
ENABLE_BYBIT_AUTOTRADE: bool = (
    os.getenv("ENABLE_BYBIT_AUTOTRADE", "false").strip().lower()
    in ("1", "true", "yes", "on")
)
# Risiko per trade dalam persen dari free balance USDT (default 1.0%).
RISK_PERCENT_PER_TRADE: float = _env_float("RISK_PERCENT_PER_TRADE", 1.0)

COINGECKO_BASE_URL: str = "https://api.coingecko.com/api/v3"
DEFILLAMA_BASE_URL: str = "https://api.llama.fi"

REQUEST_TIMEOUT: int = 30
REQUEST_RETRIES: int = 3

DISCLAIMER: str = (
    "⚠️ Disclaimer: Sinyal ini berbasis indikator otomatis & data publik. "
    "Bukan saran finansial. Selalu lakukan riset sendiri (DYOR)."
)
