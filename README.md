# BOT-Sinyal-Trading (Experiment 24/7)

Bot Telegram **Day Trading Lanjutan** yang memindai pasar crypto **24 jam non-stop** dan mengirim sinyal trading **hanya 1 koin terbaik** dengan **confidence ≥ 65%** ke chat **private**, plus hasil **evaluasi** ke group **publik** — keduanya lengkap dengan **gambar chart TradingView** (level Entry/SL/TP). Analisis **Multi-Timeframe (MTF)** dari data CoinGecko (gratis, tanpa API key berbayar). Termasuk modul **Automated Trading Bybit (opsional, default nonaktif)**.

## Fitur

- **Scan 24/7 non-stop**: `python bot.py --loop` — scan tiap `SCAN_INTERVAL_MINUTES` (default 30 menit) sepanjang hari; error per siklus tidak mematikan bot.
- **1 koin terbaik**: dari hasil scan dipilih HANYA koin BUY/SELL terkuat; dikirim **hanya bila confidence ≥ `SIGNAL_MIN_CONFIDENCE` (default 65%)**.
- **Anti-spam cooldown**: koin yang sama (symbol + arah) tidak disinyalkan ulang dalam `SIGNAL_COOLDOWN_HOURS` (default 6 jam) — tersimpan di `data/cooldown.json`.
- **Dua channel Telegram**: sinyal → chat **private** (`TELEGRAM_SIGNAL_CHAT_ID`), hasil evaluasi → group **publik** (`TELEGRAM_EVAL_CHAT_ID`).
- **Gambar chart di sinyal & evaluasi**: sinyal terbaik dilampiri chart Entry/SL/TP1/TP2; setiap hasil evaluasi juga dilampiri chart koin yang dievaluasi (via [CHART-IMG API](https://chart-img.com)).
- **Analisis Multi-Timeframe**: HTF 4H/1D menentukan **Trend Bias**, LTF 1H/15M menentukan **Entry, SL, TP**.
- **Konfluensi indikator**: Support/Resistance, Supply/Demand, SMC (BOS/CHoCH), Order Block, MACD crossover, RSI divergence, Volume/Whale Spike — dengan **Confluence Checklist** di setiap sinyal.
- **Evaluasi terjadwal**: sinyal yang berumur ≥ `EVAL_MIN_AGE_HOURS` (default 4 jam) dievaluasi (HIT TP1/TP2/SL, FLOATING) dan hasilnya dikirim ke group publik satu kali (`evaluated_at`).
- **Pencatatan hasil & win-rate kumulatif**: setiap siklus, sinyal belum tuntas dalam `RESULT_LOOKBACK_HOURS` (default 72 jam) dicek ulang — hasil final (TP1/TP2/SL) **terkunci** dan tidak pernah diturunkan; FLOATING boleh naik. Ringkasan win-rate 7 hari + ekspektasi R/trade dikirim otomatis sekali sehari ke grup evaluasi (`WINRATE_DIGEST_HOUR`, default 08:00 WIB) — dasar objektif uji kelayakan autotrade.
- **SL/TP berbasis ATR** (default SL 2× ATR, TP1 2×, TP2 3×).
- **Automated Trading Bybit (opsional)**: eksekusi market order + SL + TP1 50%/TP2 50% di Bybit Futures USDT-M — sakelar ON/OFF di `.env`, **default NONAKTIF**. Bila aktif, HANYA mengeksekusi 1 sinyal terbaik yang benar-benar dipublish ke chat private (bukan semua sinyal hasil scan).

## Cara Kerja (Mode 24/7)

Setiap siklus (`--loop`):
1. Satu panggilan CoinGecko mengambil **Top 250 koin** (market cap) + sparkline 7 hari — stablecoin disaring.
2. **Quick scan** semua koin → shortlist kandidat momentum terkuat (`MTF_SCAN_LIMIT`, default 6).
3. **Deep scan MTF** per kandidat: chart 30 hari (1H/4H/1D) + 2 hari (15M). Hitung konfluensi SMC/OB, S&D/S&R, MACD/RSI, Whale/Volume.
4. Pilih **1 koin terbaik** (BUY/SELL). Bila confidence ≥ 65% **dan** tidak dalam cooldown → kirim ke chat **private** lengkap dengan gambar chart, simpan ke history (`data/history.json`) & cooldown.
5. **Evaluasi**: sinyal tersimpan yang berumur 4–24 jam dievaluasi dengan harga terkini → hasil dikirim ke group **publik** (1 pesan per sinyal, lengkap dengan gambar chart), lalu ditandai `evaluated_at` agar tidak terkirim ulang.
6. **Refresh hasil & digest win-rate**: semua sinyal belum tuntas (≤72 jam) dicek ulang dan hasilnya dikunci di history; sekali sehari (≥ `WINRATE_DIGEST_HOUR` WIB) ringkasan win-rate 7 hari + ekspektasi R/trade dikirim ke grup evaluasi.
7. **Autotrade (opsional)**: bila aktif, HANYA sinyal terbaik yang dipublish tadi dieksekusi ke Bybit Futures.
8. Tidur `SCAN_INTERVAL_MINUTES` menit, ulangi.

Mode satu siklus (`python bot.py`, dipakai GitHub Actions): scan → evaluasi 24/7 → sinyal private → evaluasi sesi PAGI/MALAM lama ke group publik → autotrade (opsional).

## Setup

1. Buat bot di [@BotFather](https://t.me/BotFather) → salin token.
2. Cek chat ID kamu di [@userinfobot](https://t.me/userinfobot). Untuk group, tambahkan bot ke group lalu cek ID group (mis. via bot atau @getidsbot).
3. Salin `.env.example` menjadi `.env` dan isi:
   ```
   TELEGRAM_BOT_TOKEN=<token bot>
   TELEGRAM_SIGNAL_CHAT_ID=<chat private kamu — sinyal>
   TELEGRAM_EVAL_CHAT_ID=<chat group publik — evaluasi>
   ```
   (Bila salah satu kosong, fallback ke `TELEGRAM_CHAT_ID`.)
4. **(Opsional) Gambar chart di notifikasi** — daftar gratis di [chart-img.com](https://chart-img.com), salin API key, lalu isi di `.env`:
   ```
   CHART_IMG_API_KEY=<api key chart-img>
   ```
   Tanpa key, notifikasi tetap terkirim sebagai teks biasa.
5. **Jalankan 24/7**:
   ```
   venv\Scripts\python.exe bot.py --loop
   ```
   Atau satu siklus: `venv\Scripts\python.exe bot.py`
6. **(Opsional) Cadangan via GitHub Actions tiap 15 menit** — push ke repo **publik** (menit gratis tak terbatas; repo private cuma 2000 menit/bulan), workflow `daily.yml` sudah `cron: "*/15 * * * *"` (96×/hari, cadence efektif ~15–20 menit karena schedule bisa antri). Tambahkan secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_SIGNAL_CHAT_ID`, `TELEGRAM_EVAL_CHAT_ID`, opsional `CHART_IMG_API_KEY` / `COINGECKO_API_KEY`.

## Setup Automated Trading Bybit (Opsional)

> **Peringatan**: mulai dengan `ENABLE_BYBIT_AUTOTRADE=false`. Nyalakan hanya
> setelah kamu paham risiko trading futures. Uji dulu dengan akun demo/posisi kecil.

1. Login [Bybit](https://www.bybit.com) → **Akun → API Management** (https://www.bybit.com/app/user/api-management).
2. Klik **Create New Key**, pilih tipe **Unified Trading Account (UTA) / Trading API**, atur izin **Order (Trade)** saja.
3. **TIDAK ada passphrase** di Bybit API v5 — cukup **API Key + Secret Key**. Jangan pernah aktifkan **Withdraw**.
4. Isi di `.env`:
   ```
   BYBIT_API_KEY=<api key>
   BYBIT_SECRET_KEY=<secret key>
   ENABLE_BYBIT_AUTOTRADE=false     # ganti true untuk eksekusi nyata
   RISK_PERCENT_PER_TRADE=1.0       # risiko per trade (% free balance USDT)
   TELEGRAM_ADMIN_CHAT_ID=<id chat admin kamu>
   ```
5. Cara kerja: setiap sesi, sinyal **BUY/SELL yang lolos filter ketat** dieksekusi otomatis di Bybit USDT Perpetual (`defaultType=linear`):
   - **Position sizing dinamis**: `1% × saldo free USDT ÷ |Entry − SL|` → jumlah koin, dikonversi ke kontrak sesuai `contractSize` pasar.
   - **Market order** entry + **Stop Loss** terpasang langsung (full position, via field `stopLoss` order).
   - **TP1 50% & TP2 50%**: dua take-profit reduce-only di level TP sinyal.
   - Notifikasi ke admin: 🚀 `[ORDER EXECUTED]` (order terpasang) atau ⚠️ `[EXECUTION FAILED]` (saldo tidak cukup / API error).
6. Di GitHub Actions tambahkan secrets opsional: `BYBIT_API_KEY`, `BYBIT_SECRET_KEY`, `TELEGRAM_ADMIN_CHAT_ID`, dan `vars` `ENABLE_BYBIT_AUTOTRADE` (biarkan kosong/hapus vars untuk tetap nonaktif).

## Konfigurasi

| Variabel | Default | Keterangan |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | kosong | Token bot Telegram |
| `TELEGRAM_SIGNAL_CHAT_ID` | kosong | Chat **private** tujuan sinyal (fallback `TELEGRAM_CHAT_ID`) |
| `TELEGRAM_EVAL_CHAT_ID` | kosong | Group **publik** tujuan evaluasi (fallback `TELEGRAM_CHAT_ID`) |
| `TOP_COINS` | 250 | Jumlah koin dipindai |
| `TOP_SIGNALS` | 3 | Kandidat mesin (bot mengirim HANYA 1 koin terbaik) |
| `SCAN_INTERVAL_MINUTES` | 30 | Jeda antar scan (menit) pada mode `--loop` |
| `SIGNAL_MIN_CONFIDENCE` | 65 | Kirim sinyal hanya bila confidence ≥ nilai ini (%) |
| `SIGNAL_COOLDOWN_HOURS` | 6 | Jeda minimum koin yang sama (symbol+arah) boleh disinyalkan lagi (jam) |
| `EVAL_MIN_AGE_HOURS` | 4 | Umur minimum sinyal sebelum dievaluasi ke group publik (jam) |
| `EVAL_LOOKBACK_HOURS` | 24 | Batas umur sinyal yang masih dievaluasi (jam) |
| `SESSION_EVAL_MAX_AGE_DAYS` | 3 | Batas umur entri sesi PAGI/MALAM legacy yang masih dievaluasi (hari) |
| `RESULT_LOOKBACK_HOURS` | 72 | Sinyal belum tuntas terus dicek ulang sampai TP/SL dalam jendela ini (jam) |
| `WINRATE_WINDOW_DAYS` | 7 | Jendela hari ringkasan win-rate harian (digest) |
| `WINRATE_DIGEST_HOUR` | 8 | Jam WIB minimum pengiriman digest win-rate harian |
| `MTF_SCAN_LIMIT` | 6 | Kandidat deep-scan MTF |
| `CONFLUENCE_MIN` | 2 | Minimal kategori Confluence untuk BUY/SELL |
| `ATR_SL_MULT` | 2.0 | SL = ATR × pengali |
| `ATR_TP1_MULT` | 2.0 | TP1 = ATR × pengali |
| `ATR_TP2_MULT` | 3.0 | TP2 = ATR × pengali |
| `WHALE_VOLUME_MULT` | 2.5 | Ambang deteksi Whale Spike volume |
| `CHART_IMG_API_KEY` | kosong | API key CHART-IMG untuk gambar chart TradingView di notifikasi (opsional) |
| `BUY_THRESHOLD` | 3.0 | Skor minimum untuk BUY |
| `SELL_THRESHOLD` | -3.0 | Skor minimum untuk SELL |
| `ENABLE_BYBIT_AUTOTRADE` | `false` | `true` = eksekusi order NYATA di Bybit Futures |
| `BYBIT_API_KEY` | kosong | API Key Bybit (UTA, izin Order/Trade) |
| `BYBIT_SECRET_KEY` | kosong | Secret Key Bybit (tanpa passphrase) |
| `RISK_PERCENT_PER_TRADE` | 1.0 | Risiko per trade (% saldo free USDT) |
| `TELEGRAM_ADMIN_CHAT_ID` | kosong | Chat ID admin untuk laporan eksekusi (private) |

## Struktur

```
bot.py                        # Entry point: scan → pilih 1 koin terbaik (≥65%) → sinyal private → evaluasi publik → autotrade (opsional). Mode --loop = 24/7.
config.py                     # Konfigurasi & kredensial dari .env
telegram_sender.py            # Kirim pesan/foto ke Telegram + chat signal/eval terpisah + laporan admin eksekusi
execution/chart_visualizer.py # Visualisasi chart TradingView (CHART-IMG API): URL gambar + level Entry/SL/TP
execution/bybit_executor.py   # Eksekusi terpisah: Bybit Futures via CCXT (sizing, SL, TP1 50%/TP2 50%)
data/market.py                # CoinGecko (top coins, sparkline 7d, market_chart OHLC MTF)
data/history.py               # Simpan & evaluasi performa sinyal (mode sesi + mode 24/7 per sinyal)
data/history.json             # History sinyal yang dikirim
data/cooldown.py              # Cooldown anti-spam koin yang sama (24/7)
data/cooldown.json            # Data cooldown (persisten antar restart)
signals/indicators.py         # RSI, SMA, EMA, MACD, ATR, BOS/CHoCH, OB, S/R, S&D, RSI div, Whale
signals/engine.py             # Skoring MTF + Confluence Checklist → format pesan
tests/                        # Tes unit (unittest, tanpa network)
.github/workflows/daily.yml   # Opsional: scheduler 2x sehari untuk mode satu siklus
```

## Disclaimer

Sinyal berbasis indikator otomatis & data publik — bukan saran finansial. Selalu lakukan riset sendiri (DYOR).
