"""ICT / SMC analiz motoru — saf Python, harici bağımlılık yok.

Kapsanan kavramlar (kurumsal / Smart Money Concepts):
  - Market Structure: swing noktaları, BOS (Break of Structure), CHoCH (Change of Character)
  - Liquidity: buy-side/sell-side likidite havuzları ve SWEEP (stop avı / "Judas")
  - Displacement: ATR'ye göre güçlü/impulsif mum
  - FVG (Fair Value Gap): 3-mum imbalance boşluğu
  - IFVG (Inverse FVG): ihlal edilip polaritesi dönen FVG
  - Order Block (OB): impulstan önceki son zıt mum
  - Kill Zone: kurumsal aktivite zaman pencereleri (UTC)

analyze_smc(...) tüm confluence'ları toplar, skorlar ve sinyal üretir.
Eğitim/simülasyon amaçlıdır — yatırım tavsiyesi değildir.
"""

from __future__ import annotations

from strategy import ema, rsi, atr  # gösterge yardımcıları tekrar kullanılır


# ----------------------------- Market Structure -----------------------------

def swing_points(candles, k=2):
    """Fraktal swing high/low indekslerini döner. i, [i-k, i+k] içinde tepe/dip ise swing."""
    highs, lows = [], []
    n = len(candles)
    for i in range(k, n - k):
        hi = candles[i]["h"]
        lo = candles[i]["l"]
        if all(hi > candles[i - j]["h"] and hi > candles[i + j]["h"] for j in range(1, k + 1)):
            highs.append(i)
        if all(lo < candles[i - j]["l"] and lo < candles[i + j]["l"] for j in range(1, k + 1)):
            lows.append(i)
    return highs, lows


def structural_bias(candles, k=2):
    """Kalıcı yapısal bias: HH oluşursa 'bull', LL oluşursa 'bear'.

    Pullback'ler bias'ı bozmaz — ancak ters yönde bir swing (lower-low / higher-high)
    yeni yapı kırınca yön döner. Bir trader'ın 'yapı bozulmadıkça trend sürer' mantığı.
    """
    sh, sl = swing_points(candles, k)
    events = [(i, "H", candles[i]["h"]) for i in sh] + \
             [(i, "L", candles[i]["l"]) for i in sl]
    events.sort()
    bias = "neutral"
    prev_high = prev_low = None
    for _, typ, price in events:
        if typ == "H":
            if prev_high is not None and price > prev_high:
                bias = "bull"
            prev_high = price
        else:
            if prev_low is not None and price < prev_low:
                bias = "bear"
            prev_low = price
    return bias


def market_structure(candles, k=2):
    """Trend yönü + son swing seviyeleri + BOS/CHoCH bayrakları döner."""
    sh, sl = swing_points(candles, k)
    close = candles[-1]["c"]
    res = {
        "trend": "range",
        "last_sh": None, "last_sh_i": None,
        "last_sl": None, "last_sl_i": None,
        "bos_up": False, "bos_down": False, "choch": None,
    }
    if sh:
        res["last_sh_i"] = sh[-1]
        res["last_sh"] = candles[sh[-1]]["h"]
    if sl:
        res["last_sl_i"] = sl[-1]
        res["last_sl"] = candles[sl[-1]]["l"]

    # Trend: son iki swing high ve son iki swing low karşılaştırması
    trend = "range"
    if len(sh) >= 2 and len(sl) >= 2:
        hh = candles[sh[-1]]["h"] > candles[sh[-2]]["h"]
        hl = candles[sl[-1]]["l"] > candles[sl[-2]]["l"]
        lh = candles[sh[-1]]["h"] < candles[sh[-2]]["h"]
        ll = candles[sl[-1]]["l"] < candles[sl[-2]]["l"]
        if hh and hl:
            trend = "bull"
        elif lh and ll:
            trend = "bear"
    res["trend"] = trend

    # BOS: son kapanış, önceki swing seviyesini kırdı mı
    if res["last_sh"] is not None and close > res["last_sh"]:
        res["bos_up"] = True
    if res["last_sl"] is not None and close < res["last_sl"]:
        res["bos_down"] = True

    # CHoCH: mevcut trende ters ilk kırılım
    if trend == "bear" and res["bos_up"]:
        res["choch"] = "bull"
    elif trend == "bull" and res["bos_down"]:
        res["choch"] = "bear"
    return res


# ----------------------------- Liquidity Sweep -----------------------------

def liquidity_sweep(candles, k=2, lookback=12):
    """Son 'lookback' mumda likidite süpürmesi arar.

    SSL sweep (long kurulumu): bir swing low'un altına fitil at, üstünde kapan.
    BSL sweep (short kurulumu): bir swing high'ın üstüne fitil at, altında kapan.
    Döner: {'side','ref','extreme','bar_i'} veya None.
    """
    sh, sl = swing_points(candles, k)
    n = len(candles)
    start = max(k + 1, n - lookback)

    # En taze sweep'i bul (sondan geriye)
    for b in range(n - 1, start - 1, -1):
        c = candles[b]
        # SSL: b'den önce oluşmuş bir swing low'un altını süpür
        for j in reversed(sl):
            if j >= b:
                continue
            ref = candles[j]["l"]
            if c["l"] < ref and c["c"] > ref:
                return {"side": "SSL", "ref": ref, "extreme": c["l"], "bar_i": b}
            break  # sadece en yakın önceki swing low
        # BSL: b'den önce oluşmuş bir swing high'ın üstünü süpür
        for j in reversed(sh):
            if j >= b:
                continue
            ref = candles[j]["h"]
            if c["h"] > ref and c["c"] < ref:
                return {"side": "BSL", "ref": ref, "extreme": c["h"], "bar_i": b}
            break
    return None


# ----------------------------- Displacement -----------------------------

def displacement(candles, atr_val, mult=1.5, lookback=5):
    """Son 'lookback' mumda ATR'nin 'mult' katından büyük gövdeli impuls var mı."""
    if atr_val is None or atr_val <= 0:
        return None
    for i in range(len(candles) - 1, max(-1, len(candles) - 1 - lookback), -1):
        body = abs(candles[i]["c"] - candles[i]["o"])
        if body > mult * atr_val:
            direction = "up" if candles[i]["c"] > candles[i]["o"] else "down"
            return {"bar_i": i, "body": body, "direction": direction}
    return None


# ----------------------------- FVG / IFVG -----------------------------

def find_fvgs(candles, lookback=30):
    """3-mum FVG'lerini döner. Her biri: {type,'bull'/'bear', low, high, i}."""
    fvgs = []
    n = len(candles)
    start = max(1, n - lookback)
    for i in range(start, n - 1):
        a, c = candles[i - 1], candles[i + 1]
        if a["h"] < c["l"]:  # boğa FVG
            fvgs.append({"type": "bull", "low": a["h"], "high": c["l"], "i": i})
        elif a["l"] > c["h"]:  # ayı FVG
            fvgs.append({"type": "bear", "low": c["h"], "high": a["l"], "i": i})
    return fvgs


def _fvg_filled(candles, fvg):
    """FVG sonrası fiyat boşluğu kapatmış mı (tam dolum)."""
    for b in range(fvg["i"] + 2, len(candles)):
        if fvg["type"] == "bull" and candles[b]["l"] <= fvg["low"]:
            return True
        if fvg["type"] == "bear" and candles[b]["h"] >= fvg["high"]:
            return True
    return False


def active_fvg(candles, direction, lookback=30):
    """Verilen yönde, fiyatın döndüğü en taze DOLMAMIŞ FVG'yi döner (giriş bölgesi)."""
    price = candles[-1]["c"]
    want = "bull" if direction == "LONG" else "bear"
    best = None
    for fvg in find_fvgs(candles, lookback):
        if fvg["type"] != want or _fvg_filled(candles, fvg):
            continue
        # fiyat FVG'ye dönmüş/yakın mı
        in_zone = fvg["low"] <= price <= fvg["high"]
        near = fvg["low"] <= candles[-1]["l"] <= fvg["high"] or in_zone
        if near or best is None:
            best = {**fvg, "in_zone": in_zone}
    return best


def inverse_fvg(candles, direction, lookback=40):
    """IFVG: yön için ihlal edilip polaritesi dönen FVG'yi döner.

    LONG için: bir ayı FVG yukarı ihlal edilmiş -> artık boğa destek (IFVG).
    SHORT için: bir boğa FVG aşağı ihlal edilmiş -> artık ayı direnç (IFVG).
    """
    price = candles[-1]["c"]
    src = "bear" if direction == "LONG" else "bull"
    for fvg in reversed(find_fvgs(candles, lookback)):
        if fvg["type"] != src:
            continue
        violated = False
        for b in range(fvg["i"] + 2, len(candles)):
            if src == "bear" and candles[b]["c"] > fvg["high"]:
                violated = True
                break
            if src == "bull" and candles[b]["c"] < fvg["low"]:
                violated = True
                break
        if violated:
            in_zone = fvg["low"] <= price <= fvg["high"]
            return {"low": fvg["low"], "high": fvg["high"], "i": fvg["i"], "in_zone": in_zone}
    return None


# ----------------------------- Order Block -----------------------------

def order_block(candles, direction, disp_bar_i, lookback=6):
    """Displacement mumundan önceki son zıt mumu OB olarak döner.

    LONG -> son düşüş mumu (boğa OB). SHORT -> son yükseliş mumu (ayı OB).
    """
    if disp_bar_i is None:
        return None
    lo = max(0, disp_bar_i - lookback)
    for i in range(disp_bar_i - 1, lo - 1, -1):
        c = candles[i]
        if direction == "LONG" and c["c"] < c["o"]:
            return {"low": c["l"], "high": c["h"], "i": i}
        if direction == "SHORT" and c["c"] > c["o"]:
            return {"low": c["l"], "high": c["h"], "i": i}
    return None


# ----------------------------- Kill Zone -----------------------------

def in_kill_zone(now_utc, windows):
    """now_utc (datetime, UTC) verilen [ [start_min,end_min,label], ... ] pencerelerinde mi.
    start/end gün içi dakika (0-1439). Döner: eşleşen label ya da None."""
    minute = now_utc.hour * 60 + now_utc.minute
    for w in windows:
        if w[0] <= minute < w[1]:
            return w[2]
    return None


# ----------------------------- Ana motor -----------------------------

def analyze_smc(candles, now_utc, cfg=None):
    """ICT/SMC confluence motoru. Sinyal dict'i ya da None döner.

    now_utc: timezone-aware UTC datetime (kill zone için).
    """
    cfg = cfg or {}
    k = cfg.get("swing_k", 2)
    atr_p = cfg.get("atr_period", 14)
    min_bars = cfg.get("min_bars", 80)
    if len(candles) < min_bars:
        return None

    a = atr(candles, atr_p)
    if a is None or a <= 0:
        return None
    closes = [c["c"] for c in candles]
    r = rsi(closes, cfg.get("rsi_period", 14))
    price = closes[-1]

    ms = market_structure(candles, k)
    sweep = liquidity_sweep(candles, k, cfg.get("sweep_lookback", 12))
    disp = displacement(candles, a, cfg.get("disp_mult", 1.5), cfg.get("disp_lookback", 5))
    kz = in_kill_zone(now_utc, cfg.get("kill_zones", []))

    # --- Yön: likidite sweep'i birincil tetik (ICT reversal/continuation) ---
    direction = None
    if sweep and sweep["side"] == "SSL":
        direction = "LONG"      # sell-side likidite alındı -> yukarı
    elif sweep and sweep["side"] == "BSL":
        direction = "SHORT"     # buy-side likidite alındı -> aşağı
    else:
        # sweep yoksa: yapı kırılımı + displacement ile devam sinyali
        if ms["bos_up"] and disp and disp["direction"] == "up":
            direction = "LONG"
        elif ms["bos_down"] and disp and disp["direction"] == "down":
            direction = "SHORT"
    if direction is None:
        return None

    fvg = active_fvg(candles, direction, cfg.get("fvg_lookback", 30))
    ifvg = inverse_fvg(candles, direction, cfg.get("fvg_lookback", 40))
    ob = order_block(candles, direction, disp["bar_i"] if disp else None)

    # --- Confluence skoru (ağırlıklar config'ten) ---
    w = cfg.get("weights", {})
    confluences = []
    score = 0.0

    if kz:
        score += w.get("kill_zone", 2.0); confluences.append(f"KillZone ({kz})")
    if sweep:
        score += w.get("sweep", 2.5)
        confluences.append(f"{sweep['side']} likidite süpürüldü @ {sweep['ref']:.2f}")
    struct_ok = (direction == "LONG" and (ms["bos_up"] or ms["choch"] == "bull")) or \
                (direction == "SHORT" and (ms["bos_down"] or ms["choch"] == "bear"))
    if struct_ok:
        score += w.get("structure", 2.0)
        tag = "CHoCH" if ms["choch"] else "BOS"
        confluences.append(f"{tag} {'yukarı' if direction=='LONG' else 'aşağı'}")
    if disp and ((direction == "LONG") == (disp["direction"] == "up")):
        score += w.get("displacement", 1.0); confluences.append("Displacement (impuls)")
    if fvg:
        score += w.get("fvg", 2.0)
        confluences.append(f"FVG giriş bölgesi {fvg['low']:.2f}-{fvg['high']:.2f}"
                           + (" (fiyat içinde)" if fvg.get("in_zone") else ""))
    if ifvg:
        score += w.get("ifvg", 1.5)
        confluences.append(f"IFVG {ifvg['low']:.2f}-{ifvg['high']:.2f}")
    if ob:
        score += w.get("order_block", 1.5)
        confluences.append(f"Order Block {ob['low']:.2f}-{ob['high']:.2f}")
    if r is not None:
        if direction == "LONG" and r < cfg.get("rsi_long_max", 75):
            score += w.get("rsi", 0.5)
        elif direction == "SHORT" and r > cfg.get("rsi_short_min", 25):
            score += w.get("rsi", 0.5)

    score = round(min(score, 10.0), 1)

    # --- Giriş / SL / TP (yapı + likidite temelli) ---
    entry = price
    buf = cfg.get("sl_buffer_atr", 0.25) * a
    if direction == "LONG":
        stop_ref = sweep["extreme"] if sweep else (ob["low"] if ob else price - a)
        sl = min(stop_ref, price - 0.5 * a) - buf
    else:
        stop_ref = sweep["extreme"] if sweep else (ob["high"] if ob else price + a)
        sl = max(stop_ref, price + 0.5 * a) + buf

    risk = abs(entry - sl)
    if risk <= 0:
        return None
    tp1 = entry + (1.5 if direction == "LONG" else -1.5) * risk
    tp2 = entry + (2.5 if direction == "LONG" else -2.5) * risk

    # Hedef likidite (varsa opposing swing) — bilgi amaçlı
    liq_target = ms["last_sh"] if direction == "LONG" else ms["last_sl"]

    return {
        "engine": "ICT/SMC",
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "rr1": round(abs(tp1 - entry) / risk, 2),
        "rr2": round(abs(tp2 - entry) / risk, 2),
        "confidence": score,
        "rsi": round(r, 1) if r is not None else None,
        "atr": a,
        "kill_zone": kz,
        "confluences": confluences,
        "liq_target": liq_target,
        "trend": ms["trend"],
        "reason": " + ".join(confluences) if confluences else "confluence yok",
    }
