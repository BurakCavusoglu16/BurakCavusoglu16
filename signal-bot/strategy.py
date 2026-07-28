"""Scalp sinyal mantığı — saf Python (harici bağımlılık yok).

Tüm fonksiyonlar test edilebilir olsun diye OHLCV listeleri üzerinde çalışır.
Girdi: kapanmış mumların listesi, en eskiden en yeniye sıralı.
Her mum: {"t": epoch_sn, "o":.., "h":.., "l":.., "c":.., "v":..}

Strateji (5 dakikalık scalp):
  - Trend yönü:     EMA50 vs EMA200 (bias) + fiyatın EMA50'ye göre konumu
  - Giriş tetiği:   EMA9 x EMA21 taze kesişimi (son kapanan mumda oluşmuş)
  - Momentum filtresi: RSI14 aşırı bölgede olmamalı
  - Volatilite:     ATR14 -> SL/TP mesafeleri
Bu bir eğitim/simülasyon aracıdır, yatırım tavsiyesi değildir.
"""

from __future__ import annotations


def ema(values, period):
    """Üstel hareketli ortalama. Her indeks için (ilk period-1 None) döner."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [None] * len(values)
    # ilk EMA çekirdeği = ilk 'period' değerin basit ortalaması
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes, period=14):
    """Wilder RSI. Son değeri döndürür (yeterli veri yoksa None)."""
    if len(closes) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        ch = closes[i] - closes[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gain = ch if ch > 0 else 0.0
        loss = -ch if ch < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles, period=14):
    """Wilder ATR. Son değeri döndürür (yeterli veri yoksa None)."""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["h"]
        low = candles[i]["l"]
        prev_c = candles[i - 1]["c"]
        tr = max(h - low, abs(h - prev_c), abs(low - prev_c))
        trs.append(tr)
    atr_val = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr_val = (atr_val * (period - 1) + trs[i]) / period
    return atr_val


def _crossed_up(fast, slow, i):
    """i indeksinde fast, slow'u yukarı kesti mi (i-1'de altında, i'de üstünde)."""
    if None in (fast[i], slow[i], fast[i - 1], slow[i - 1]):
        return False
    return fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]


def _crossed_down(fast, slow, i):
    if None in (fast[i], slow[i], fast[i - 1], slow[i - 1]):
        return False
    return fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]


def analyze(candles, cfg=None):
    """OHLCV listesini analiz eder. Sinyal varsa dict, yoksa None döner.

    Dönen dict: yön, entry, sl, tp1, tp2, rr1, rr2, confidence, rsi, atr, reason
    """
    cfg = cfg or {}
    ema_fast_p = cfg.get("ema_fast", 9)
    ema_mid_p = cfg.get("ema_mid", 21)
    ema_slow_p = cfg.get("ema_slow", 50)
    ema_bias_p = cfg.get("ema_bias", 200)
    rsi_p = cfg.get("rsi_period", 14)
    atr_p = cfg.get("atr_period", 14)
    sl_mult = cfg.get("sl_atr_mult", 1.0)
    tp1_mult = cfg.get("tp1_atr_mult", 1.5)
    tp2_mult = cfg.get("tp2_atr_mult", 2.5)
    min_bars = ema_bias_p + 5

    if len(candles) < min_bars:
        return None

    closes = [c["c"] for c in candles]
    ef = ema(closes, ema_fast_p)
    em = ema(closes, ema_mid_p)
    es = ema(closes, ema_slow_p)
    eb = ema(closes, ema_bias_p)
    r = rsi(closes, rsi_p)
    a = atr(candles, atr_p)
    if None in (ef[-1], em[-1], es[-1], eb[-1]) or r is None or a is None or a <= 0:
        return None

    i = len(candles) - 1  # son kapanan mum
    price = closes[-1]
    long_bias = es[-1] > eb[-1] and price > es[-1]
    short_bias = es[-1] < eb[-1] and price < es[-1]

    direction = None
    if _crossed_up(ef, em, i) and long_bias and r < cfg.get("rsi_long_max", 72):
        direction = "LONG"
    elif _crossed_down(ef, em, i) and short_bias and r > cfg.get("rsi_short_min", 28):
        direction = "SHORT"
    if direction is None:
        return None

    # Güven skoru: filtrelerin ne kadar güçlü hizalandığı (0-10)
    conf = 5.0
    slope = es[-1] - es[-5] if es[-5] is not None else 0.0
    if direction == "LONG":
        if slope > 0:
            conf += 1.5
        if 50 <= r <= 65:
            conf += 1.5
        if price > em[-1]:
            conf += 1.0
        if (price - es[-1]) / a < 1.5:  # trendden çok uzaklaşmamış = daha iyi giriş
            conf += 1.0
    else:
        if slope < 0:
            conf += 1.5
        if 35 <= r <= 50:
            conf += 1.5
        if price < em[-1]:
            conf += 1.0
        if (es[-1] - price) / a < 1.5:
            conf += 1.0
    conf = round(min(conf, 10.0), 1)

    if direction == "LONG":
        entry = price
        sl = entry - sl_mult * a
        tp1 = entry + tp1_mult * a
        tp2 = entry + tp2_mult * a
    else:
        entry = price
        sl = entry + sl_mult * a
        tp1 = entry - tp1_mult * a
        tp2 = entry - tp2_mult * a

    risk = abs(entry - sl)
    rr1 = round(abs(tp1 - entry) / risk, 2) if risk else 0
    rr2 = round(abs(tp2 - entry) / risk, 2) if risk else 0

    return {
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "rr1": rr1,
        "rr2": rr2,
        "confidence": conf,
        "rsi": round(r, 1),
        "atr": a,
        "ema_slope": slope,
        "reason": (
            f"EMA{ema_fast_p}x{ema_mid_p} taze {'yukarı' if direction=='LONG' else 'aşağı'} "
            f"kesişim, {'EMA50>EMA200' if direction=='LONG' else 'EMA50<EMA200'} bias, "
            f"RSI {round(r,1)}"
        ),
    }
