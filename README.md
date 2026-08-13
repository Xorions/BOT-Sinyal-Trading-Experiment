# BOT-Sinyal-Trading

Bot Telegram **Day Trading Lanjutan** yang mengirim sinyal trading crypto **2x sehari** (07:00 WIB Sesi Pagi & 19:00 WIB Sesi Malam) berdasarkan analisis **Multi-Timeframe (MTF)** dari data CoinGecko (gratis, tanpa API key berbayar). Termasuk modul **Automated Trading Bitget (opsional, default nonaktif)** yang mengeksekusi sinyal BUY/SELL yang lolos filter ketat ke Bitget Futures USDT-M.

## Fitur

- **Analisis Multi-Timeframe**: HTF 4H/1D menentukan **Trend Bias**, LTF 1H/15M menentukan **Entry, SL, TP**.
- **Konfluensi indikator**:
  - Utama: Support/Resistance, Supply/Demand, SMC (BOS/CHoCH), Order Block (bullish/bearish).
  - Pendukung: MACD crossover, RSI divergence, deteksi Volume/Whale Spike.
- **Confluence Checklist** di setiap sinyal: SMC/OB, S&D/S&R, MACD/RSI, Whale/Vol.
- **Evaluasi sinyal sesi sebelumnya** di bagian atas pesan (HIT TP1/TP2/SL, FLOATING) — Sesi Malam mengevaluasi Sesi Pagi, Sesi Pagi mengevaluasi Sesi Malam.
- **SL/TP berbasis ATR** (default SL 1.5× ATR, TP1 2×, TP2 3×).
- **Automated Trading Bitget (opsional)**: eksekusi market order + SL + TP1 50%/TP2 50% otomatis di Bitget Futures, position size berbasis risk (1% saldo), sakelar ON/OFF di `.env`, laporan live 🚀/⚠️ ke chat admin. Modul terpisah (`execution/`) sehingga tidak mengganggu bot sinyal harian.

## Cara Kerja

Setiap sesi (07:00 & 19:00 WIB), GitHub Actions menjalankan `bot.py`:
1. Satu panggilan CoinGecko mengambil **Top 250 koin** (market cap) + sparkline 7 hari — stablecoin disaring.
2. **Quick scan** semua koin → shortlist kandidat momentum terkuat (`MTF_SCAN_LIMIT`, default 6).
3. **Deep scan MTF** per kandidat: chart 30 hari (1H/4H/1D) + 2 hari (15M). Hitung konfluensi SMC/OB, S&D/S&R, MACD/RSI, Whale/Volume.
4. **Evaluasi sesi sebelumnya**: membaca `data/history.json` (per kunci tanggal+sesi), membandingkan Entry/SL/TP dengan harga terkini → hasil HIT TP1/TP2/SL atau FLOATING, ditampilkan paling atas.
5. Pilih **TOP 5 sinyal terbaik** (BUY/LONG & SELL/SHORT paling solid), kirim ke Telegram, simpan sinyal sesi ini ke history (di-commit kembali agar terseusur antar sesi).

## Setup

1. Buat bot di [@BotFather](https://t.me/BotFather) → salin token.
2. Cek chat ID kamu di [@userinfobot](https://t.me/userinfobot).
3. Salin `.env.example` menjadi `.env` dan isi:
   ```
   TELEGRAM_BOT_TOKEN=<token bot>
   TELEGRAM_CHAT_ID=<id chat kamu>
   ```
4. Uji lokal: `venv\Scripts\python.exe bot.py`
5. Push ke GitHub, lalu tambahkan **repository secrets**:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - Opsional: `vars` `MTF_SCAN_LIMIT`, `CONFLUENCE_MIN`.

## Setup Automated Trading Bitget (Opsional)

> **Peringatan**: mulai dengan `ENABLE_BITGET_AUTOTRADE=false`. Nyalakan hanya
> setelah kamu paham risiko trading futures. Uji dulu dengan akun demo/posisi kecil.

1. Login [Bitget](https://www.bitget.com) → **Aplikasi → API Trading**.
2. Pilih tipe **Futures/Contract**, buat **PASS PHRASE** sendiri (disimpan sekali saat pembuatan — ini BUKAN sandi akun).
3. Aktifkan izin **Read** + **Trade** saja. Jangan pernah aktifkan **Withdraw**.
4. Isi di `.env`:
   ```
   BITGET_API_KEY=<api key>
   BITGET_SECRET_KEY=<secret key>
   BITGET_PASSPHRASE=<pass phrase>
   ENABLE_BITGET_AUTOTRADE=false     # ganti true untuk eksekusi nyata
   RISK_PERCENT_PER_TRADE=1.0        # risiko per trade (% free balance USDT)
   TELEGRAM_ADMIN_CHAT_ID=<id chat admin kamu>
   ```
5. Cara kerja: setiap sesi, sinyal **BUY/SELL yang lolos filter ketat** dieksekusi otomatis:
   - **Position sizing dinamis**: `1% × saldo free USDT ÷ |Entry − SL|` → jumlah koin.
   - **Market order** entry + **Stop Loss** terpasang langsung (full position).
   - **TP1 50% & TP2 50%**: dua take-profit reduce-only di level TP sinyal.
   - Notifikasi ke admin: 🚀 `[ORDER EXECUTED]` (order terpasang) atau ⚠️ `[EXECUTION FAILED]` (saldo tidak cukup / API error).
6. Di GitHub Actions tambahkan secrets opsional: `BITGET_API_KEY`, `BITGET_SECRET_KEY`, `BITGET_PASSPHRASE`, `TELEGRAM_ADMIN_CHAT_ID`, dan `vars` `ENABLE_BITGET_AUTOTRADE` (biarkan kosong/hapus vars untuk tetap nonaktif).

## Konfigurasi

| Variabel | Default | Keterangan |
|---|---|---|
| `TOP_COINS` | 250 | Jumlah koin dipindai |
| `TOP_SIGNALS` | 5 | Jumlah sinyal dikirim |
| `MTF_SCAN_LIMIT` | 6 | Kandidat deep-scan MTF |
| `CONFLUENCE_MIN` | 2 | Minimal kategori Confluence untuk BUY/SELL |
| `ATR_SL_MULT` | 1.5 | SL = ATR × pengali |
| `ATR_TP1_MULT` | 2.0 | TP1 = ATR × pengali |
| `ATR_TP2_MULT` | 3.0 | TP2 = ATR × pengali |
| `WHALE_VOLUME_MULT` | 2.5 | Ambang deteksi Whale Spike volume |
| `BUY_THRESHOLD` | 3.0 | Skor minimum untuk BUY |
| `SELL_THRESHOLD` | -3.0 | Skor minimum untuk SELL |
| `ENABLE_BITGET_AUTOTRADE` | `false` | `true` = eksekusi order NYATA di Bitget Futures |
| `BITGET_API_KEY` | kosong | API Key Bitget (tipe Futures) |
| `BITGET_SECRET_KEY` | kosong | Secret Key Bitget |
| `BITGET_PASSPHRASE` | kosong | Passphrase API Bitget |
| `RISK_PERCENT_PER_TRADE` | 1.0 | Risiko per trade (% saldo free USDT) |
| `TELEGRAM_ADMIN_CHAT_ID` | kosong | Chat ID admin untuk laporan eksekusi (private) |

## Struktur

```
bot.py                        # Entry point: quick scan → deep MTF scan → evaluasi → kirim → autotrade (opsional)
config.py                     # Konfigurasi & kredensial dari .env
telegram_sender.py            # Kirim pesan ke Telegram + laporan admin eksekusi (ORDER EXECUTED / FAILED)
execution/bitget_executor.py  # Eksekusi terpisah: Bitget Futures via CCXT (sizing, SL, TP1 50%/TP2 50%)
data/market.py                # CoinGecko (top coins, sparkline 7d, market_chart OHLC MTF)
data/history.py               # Simpan & evaluasi performa sinyal per sesi
data/history.json             # History sinyal yang dikirim (di-commit tiap sesi)
signals/indicators.py         # RSI, SMA, EMA, MACD, ATR, BOS/CHoCH, OB, S/R, S&D, RSI div, Whale
signals/engine.py             # Skoring MTF + Confluence Checklist → format pesan
tests/                        # Tes unit (unittest, tanpa network) — termasuk mock eksekutor Bitget
.github/workflows/daily.yml   # Scheduler 2x sehari (07:00 & 19:00 WIB)
```

## Disclaimer

Sinyal berbasis indikator otomatis & data publik — bukan saran finansial. Selalu lakukan riset sendiri (DYOR).
