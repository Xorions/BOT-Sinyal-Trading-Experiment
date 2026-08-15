# AUDIT — Kualifikasi Sinyal (Confluence, Filter, SL/ATR)

Tanggal audit: 14 Agu 2026
Scope: `signals/engine.py`, `signals/indicators.py`, `config.py`, evaluasi `data/history.json`
Catatan khusus: proyek ini memuat **Automated Trading OKX** (`execution/okx_executor.py`)
— filter kualitas sinyal adalah pengaman utama terhadap order NYATA di OKX Futures.

---

## 1. Temuan Utama: Kenapa Sinyal Berkonfluensi Lemah Tetap Terkirim

### Root cause #1 — `CONFLUENCE_MIN` menghitung **item**, bukan **kategori** (PENYEBAB UTAMA)

Di `signals/engine.py` (fungsi `build_final_signal`):

```python
aligned_total = sum(ok for ok, _ in checklist.values())   # jumlah ITEM cek selaras
...
if action != ACTION_NEUTRAL and aligned_total < CONFLUENCE_MIN:  # CONFLUENCE_MIN = 2
    action = ACTION_NEUTRAL
```

Satu kategori SMC/OB berisi **2 item** (BOS/CHoCH + Order Block). Artinya koin dengan
SMC/OB 2/2 sendirian sudah menghasilkan `aligned_total = 2` dan lolos gerbang
`CONFLUENCE_MIN = 2`, meskipun:

- S&D/S&R = **0/2**
- MACD/RSI = **0/2**
- Whale/Vol = **0/1**

Pola ini persis terlihat pada sinyal #PUMP (confidence 76), #BEAT, #KAG, #HOLO,
#VELVET, dll di history: checklist didominasi SMC/OB saja. Berbahaya ganda di
proyek ini karena sinyal yang lolos **bisa dieksekusi otomatis ke OKX**.

### Root cause #2 — Ambang skor terlalu mudah dilampaui oleh quick scan

`BUY_THRESHOLD = 3.0`. Quick scan sendiri bisa menghasilkan hingga ±8.5 poin
(RSI 2.0 + trend 1.5 + momentum 1j/24j/7d 3.5 + volume 1.5). Ditambah poin MTF
(HTF bias 1.5 + BOS 1.0 + OB 1.0 = 3.5 tanpa satu pun konfirmasi S&D/MACD/RSI),
`total >= 3.0` hampir selalu tercapai. **Gerbang kualitas satu-satunya adalah
checklist, dan gerbang itu bocor (lihat root cause #1).**

### Root cause #3 — Konfirmasi inti (trend context) diabaikan

Tidak ada aturan yang mensyaratkan konfirmasi dari kategori yang membuktikan
konteks tren/level: **S&D/S&R (level) dan MACD/RSI (momentum)**. Sinyal bisa
"tepat" secara struktur SMC tetapi melawan level/divergensi yang jelas — kombinasi
yang paling sering berakhir HIT SL (dan rugi riil bila autotrade aktif).

### Root cause #4 — SL terlalu rapat untuk volatilitas tinggi

- `ATR_SL_MULT = 1.5` (default) → SL hanya 1.5×ATR(1H). Untuk altcoin di rejim
  volatilitas tinggi, candle 1H biasa bergerak 2–6%; SL sub-1% mudah di-wick.
- Contoh dari history.json (jarak SL dari entry):
  - PENGU 08-08 MALAM: **0.64%**
  - TAO 08-09 MALAM: **0.87%**
  - CRV 08-09 MALAM: **0.95%**
  - WLD 08-12 PAGI: **1.09%**
- SL juga **tidak mempertimbangkan swing low/high terdekat** → harga menguji
  level lalu kembali, tapi posisi sudah kena stop (HIT SL) padahal skenario
  yang diprediksi tetap terjadi.

### Root cause #5 — Definisi "aligned" RSI terlalu longgar

`rsi_bull_aligned = rsi_div == BULLISH_DIV or rsi < 35`. Ambang 35 (bukan 30)
menjadikan RSI "mendekati oversold" dihitung sebagai konfirmasi penuh MACD/RSI,
menggelembungkan angka 1/2 yang seharusnya 0/2.

---

## 2. Perubahan yang Diterapkan

| # | Perubahan | File |
|---|-----------|------|
| 1 | **Gate konfluensi inti**: BUY/SELL wajib minimal `REQUIRE_CONFLUENCE_CORE` (default 1) cek selaras dari **S&D/S&R atau MACD/RSI**. Jika tidak, status diturunkan ke NEUTRAL (WATCHLIST) + alasan ditambahkan ke catatan sinyal. | `signals/engine.py` `build_final_signal`, `config.py` |
| 2 | **`ATR_SL_MULT` 1.5x → 2.0x** (env-configurable) | `config.py` |
| 3 | **SL dinamis di luar swing low/high terdekat**: SL = max(ATR-SL, swing-low − `SWING_SL_BUFFER_MULT`×ATR) untuk BUY (mirror untuk SELL), dibatasi `MAX_SL_MULT` = 2.5×ATR agar risk-reward tetap sehat | `signals/engine.py` `_atr_levels`, `config.py` |
| 4 | **RSI aligned 35/65 → 30/70** (selaras dengan semantik oversold/overbought quick scan) | `signals/engine.py` `analyze_mtf` |
| 5 | Konfigurasi baru ditambahkan ke `.env.example` & workflow GitHub Actions | `.env.example`, `.github/workflows/daily.yml` |
| 6 | Test unit baru: demosi SMC-only, promosi dengan 1 cek inti, SL di luar swing low/high, cap SL | `tests/test_engine.py` |

### Dampak pada alur (termasuk autotrade OKX)
- Koin dengan SMC/OB 2/2 saja → **WATCHLIST (NEUTRAL)** → tidak dikirim sebagai
  BUY/SELL **dan tidak dieksekusi** oleh `execution/okx_executor.py`
  (`bot.py::run_autotrade` sudah melewatkan action selain BUY/SELL).
- Koin dengan SMC/OB 2/2 + minimal 1 cek S&D/S&R **atau** MACD/RSI → tetap TRADE.
- SL lebih lebar secara default (2×ATR) dan diposisikan di luar level kunci bila
  memungkinkan (maks 2.5×ATR). Position sizing OKX otomatis menyesuaikan:
  stop lebih lebar → ukuran posisi lebih kecil, risiko per trade tetap 1%.

---

## 3. Rekomendasi Lanjutan (di luar scope perubahan ini)

1. **Pertimbangkan R:R minimum**: koin yang membutuhkan SL > 2×ATR (entry mengejar
   harga, jauh dari level) sebaiknya diturunkan ke WATCHLIST juga.
2. **S&D/S&R perlu dikencangkan**: `near_support` hanya mensyaratkan jarak ≤ 1×ATR;
   nilai 1/2 dari kategori ini saat ini cukup lunak. Bisa diuji naikkan ke
   `REQUIRE_CONFLUENCE_CORE = 2` bila tingkat HIT SL masih tinggi.
3. **Backtest historis**: jalankan evaluasi ulang `data/history.json` dengan filter
   baru (simulasi) untuk mengukur berapa sinyal HIT SL yang akan tersaring.
4. **Autotrade**: jangan nyalakan `ENABLE_OKX_AUTOTRADE=true` sebelum bot berjalan
   beberapa sesi dengan filter baru dan hasil evaluasi menunjukkan win-rate sehat.

---

## 4. Ringkasan Penyebab Utama (TL;DR)

1. **Gerbang `CONFLUENCE_MIN` menghitung item, bukan kategori** → SMC/OB 2/2 sendirian cukup untuk lolos.
2. **Ambang skor 3.0 terlalu mudah** dicapai oleh momentum quick scan + SMC.
3. **Tidak ada syarat konfirmasi inti** (S&D/S&R / MACD/RSI) → sinyal melawan konteks level & momentum tetap dikirim.
4. **SL 1.5×ATR terlalu rapat** dan tanpa perlindungan swing level → wick-out = HIT SL.
5. **RSI "mendekati oversold" (35) dihitung sebagai konfirmasi** → angka konfluensi MACD/RSI terinflasi.

Semua poin 1–5 sudah ditangani pada bagian 2.