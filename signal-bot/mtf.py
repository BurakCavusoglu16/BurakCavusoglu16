"""Çok Zaman Dilimli (MTF) top-down analiz — gerçek trader iş akışı.

Mantık:
  1) HTF (yüksek zaman dilimi) BIAS: yapı (BOS/CHoCH) + premium/discount + POI listesi
  2) Fiyat, bias yönündeki bir HTF POI'sine (FVG / Order Block) GELDİ mi? (gerekli alan)
  3) O alan içindeyken LTF (düşük zaman dilimi) ONAY: likidite sweep + CHoCH + FVG entry
  4) Entry / SL / TP: LTF yapısı + HTF likidite hedefi
  5) Confluence skoru -> emir kartı

Alan oluşmadan (fiyat HTF POI'sinde değilken) ya da LTF onayı yokken sinyal ÜRETMEZ —
tıpkı bir trader'ın "seviyeye gelsin, sonra teyit arayayım" demesi gibi.
Eğitim/simülasyon amaçlıdır — yatırım tavsiyesi değildir.
"""

from __future__ import annotations

import smc


# ------------------------------- HTF BIAS -------------------------------

def _equilibrium(candles, ms, lookback):
    """Güncel işlem bacağının equilibrium'u (%50). Son swing high/low varsa onları,
    yoksa lookback penceresini kullanır. (range_high, range_low, eq) döner."""
    if ms["last_sh"] is not None and ms["last_sl"] is not None and ms["last_sh"] > ms["last_sl"]:
        hi, lo = ms["last_sh"], ms["last_sl"]
    else:
        window = candles[-lookback:] if len(candles) > lookback else candles
        hi = max(c["h"] for c in window)
        lo = min(c["l"] for c in window)
    return hi, lo, (hi + lo) / 2.0


def htf_bias(candles, cfg=None):
    """HTF bias + anlamlı POI'leri döner. POI filtreleri: bias yönü, discount/premium
    hizası, ATR'ye göre minimum FVG genişliği."""
    cfg = cfg or {}
    k = cfg.get("swing_k", 2)
    ms = smc.market_structure(candles, k)
    sbias = smc.structural_bias(candles, k)
    price = candles[-1]["c"]
    a = smc.atr(candles, cfg.get("atr_period", 14)) or (abs(price) * 0.002)
    hi, lo, eq = _equilibrium(candles, ms, cfg.get("range_lookback", 60))
    zone = "discount" if price < eq else "premium"

    # Kalıcı yapısal bias birincil
    bias = "LONG" if sbias == "bull" else "SHORT" if sbias == "bear" else "neutral"

    # Bias yönündeki ANLAMLI POI'ler: yeterince geniş & dolmamış FVG + order block,
    # ve doğru premium/discount yarısında (LONG->discount, SHORT->premium)
    pois = []
    want = "bull" if bias == "LONG" else "bear" if bias == "SHORT" else None
    min_w = cfg.get("min_fvg_atr", 0.5) * a
    if want:
        for fvg in smc.find_fvgs(candles, cfg.get("fvg_lookback", 40)):
            if fvg["type"] != want or smc._fvg_filled(candles, fvg):
                continue
            if (fvg["high"] - fvg["low"]) < min_w:
                continue                                  # gürültü boyutu FVG'yi ele
            mid = (fvg["low"] + fvg["high"]) / 2.0
            if (bias == "LONG" and mid <= eq) or (bias == "SHORT" and mid >= eq):
                pois.append({"kind": "FVG", "low": fvg["low"], "high": fvg["high"], "dir": want})
        disp = smc.displacement(candles, a, cfg.get("disp_mult", 1.5), cfg.get("disp_lookback", 8))
        ob = smc.order_block(candles, bias, disp["bar_i"] if disp else None)
        if ob:
            mid = (ob["low"] + ob["high"]) / 2.0
            if (bias == "LONG" and mid <= eq) or (bias == "SHORT" and mid >= eq):
                pois.append({"kind": "OB", "low": ob["low"], "high": ob["high"], "dir": want})
        rb = smc.rejection_block(candles, bias, k, cfg.get("rb_lookback", 20),
                                 cfg.get("rb_wick_ratio", 1.0))
        if rb:
            mid = (rb["low"] + rb["high"]) / 2.0
            if (bias == "LONG" and mid <= eq) or (bias == "SHORT" and mid >= eq):
                pois.append({"kind": "RB", "low": rb["low"], "high": rb["high"], "dir": want})
        bb = smc.breaker_block(candles, bias, k, cfg.get("breaker_lookback", 40))
        if bb:
            mid = (bb["low"] + bb["high"]) / 2.0
            if (bias == "LONG" and mid <= eq) or (bias == "SHORT" and mid >= eq):
                pois.append({"kind": "Breaker", "low": bb["low"], "high": bb["high"], "dir": want})

    # Aktif POI: fiyat gerçekten içinde VE doğru premium/discount bölgesinde
    active = None
    zone_ok = (bias == "LONG" and zone == "discount") or (bias == "SHORT" and zone == "premium")
    if zone_ok:
        for p in pois:
            if p["low"] <= price <= p["high"]:
                active = p
                break

    liq_target = ms["last_sh"] if bias == "LONG" else ms["last_sl"] if bias == "SHORT" else None

    return {
        "bias": bias, "trend": ms["trend"], "equilibrium": eq,
        "range_high": hi, "range_low": lo, "zone": zone,
        "pois": pois, "active_poi": active, "liq_target": liq_target,
        "choch": ms["choch"], "bos_up": ms["bos_up"], "bos_down": ms["bos_down"],
    }


# ------------------------------- LTF ENTRY -------------------------------

def ltf_confirmation(candles, bias, cfg=None):
    """LTF'de bias yönünde onay arar: sweep ve/veya CHoCH + FVG. dict ya da None."""
    cfg = cfg or {}
    k = cfg.get("swing_k", 2)
    ms = smc.market_structure(candles, k)
    sweep = smc.liquidity_sweep(candles, k, cfg.get("sweep_lookback", 12))
    a = smc.atr(candles, cfg.get("atr_period", 14))
    disp = smc.displacement(candles, a, cfg.get("disp_mult", 1.3), cfg.get("disp_lookback", 5))

    sweep_ok = sweep and ((bias == "LONG" and sweep["side"] == "SSL") or
                          (bias == "SHORT" and sweep["side"] == "BSL"))
    choch_ok = (bias == "LONG" and (ms["choch"] == "bull" or ms["bos_up"])) or \
               (bias == "SHORT" and (ms["choch"] == "bear" or ms["bos_down"]))
    if not (sweep_ok or choch_ok):
        return None  # alan oluştu ama LTF teyidi yok -> entry yok

    fvg = smc.active_fvg(candles, bias, cfg.get("fvg_lookback", 30))
    ob = smc.order_block(candles, bias, disp["bar_i"] if disp else None)
    rb = smc.rejection_block(candles, bias, k, cfg.get("rb_lookback", 20),
                             cfg.get("rb_wick_ratio", 1.0))
    bb = smc.breaker_block(candles, bias, k, cfg.get("breaker_lookback", 40))
    return {
        "sweep": sweep if sweep_ok else None,
        "choch": ms["choch"] if choch_ok else None,
        "bos": (ms["bos_up"] if bias == "LONG" else ms["bos_down"]),
        "fvg": fvg, "ob": ob, "rb": rb, "bb": bb, "atr": a, "ms": ms,
    }


# ------------------------------- ORCHESTRATOR -------------------------------

def analyze_mtf(htf_candles, ltf_candles, now_utc, cfg=None):
    """Top-down MTF analizi. Sinyal dict'i ya da None döner."""
    cfg = cfg or {}
    htf_cfg = cfg.get("htf", {})
    ltf_cfg = cfg.get("ltf", {})

    if len(htf_candles) < htf_cfg.get("min_bars", 60):
        return None
    if len(ltf_candles) < ltf_cfg.get("min_bars", 80):
        return None

    htf = htf_bias(htf_candles, htf_cfg)
    if htf["bias"] == "neutral":
        return None                       # net HTF bias yok -> bekle
    if htf["active_poi"] is None:
        return None                       # fiyat HTF POI'sinde değil -> alan oluşmadı, bekle

    conf = ltf_confirmation(ltf_candles, htf["bias"], ltf_cfg)
    if conf is None:
        return None                       # alan var ama LTF onayı yok -> bekle

    bias = htf["bias"]
    price = ltf_candles[-1]["c"]
    a = conf["atr"] or smc.atr(ltf_candles, 14) or (abs(price) * 0.001)
    buf = ltf_cfg.get("sl_buffer_atr", 0.25) * a
    poi = htf["active_poi"]

    # --- SL: LTF sweep extreme / POI sınırı ötesi ---
    if bias == "LONG":
        stop_ref = min(x for x in [
            conf["sweep"]["extreme"] if conf["sweep"] else None,
            conf["rb"]["low"] if conf["rb"] else None,
            poi["low"], price - 0.5 * a] if x is not None)
        sl = stop_ref - buf
    else:
        stop_ref = max(x for x in [
            conf["sweep"]["extreme"] if conf["sweep"] else None,
            conf["rb"]["high"] if conf["rb"] else None,
            poi["high"], price + 0.5 * a] if x is not None)
        sl = stop_ref + buf

    entry = price
    # ICT rafine giriş: RB varsa Mean Threshold (fitil %50'si) daha iyi R verir.
    # Sadece fiyatın henüz ulaşmadığı, doğru taraftaki MT'yi limit olarak öner.
    entry_mt = None
    if conf["rb"] and conf["rb"].get("mt") is not None:
        mt = conf["rb"]["mt"]
        if (bias == "LONG" and sl < mt < price) or (bias == "SHORT" and price < mt < sl):
            entry_mt = mt

    risk = abs(entry - sl)
    if risk <= 0:
        return None

    # --- TP: HTF likidite hedefi + R katları ---
    tp1 = entry + (1.5 if bias == "LONG" else -1.5) * risk
    liq = htf["liq_target"]
    if liq is not None and ((bias == "LONG" and liq > entry) or (bias == "SHORT" and liq < entry)):
        tp2 = liq                          # HTF likidite hedefi
    else:
        tp2 = entry + (2.5 if bias == "LONG" else -2.5) * risk

    # --- Confluence skoru ---
    w = cfg.get("weights", {})
    confl = []
    score = 0.0
    kz = smc.in_kill_zone(now_utc, cfg.get("kill_zones", []))
    if kz:
        score += w.get("kill_zone", 1.5); confl.append(f"KillZone ({kz})")
    score += w.get("htf_bias", 2.0)
    confl.append(f"HTF bias {bias} (trend {htf['trend']})")
    if (bias == "LONG" and htf["zone"] == "discount") or (bias == "SHORT" and htf["zone"] == "premium"):
        score += w.get("premium_discount", 1.5)
        confl.append(f"HTF {htf['zone']} bölgesi (eq {htf['equilibrium']:.2f})")
    score += w.get("htf_poi", 2.0)
    confl.append(f"HTF {poi['kind']} POI {poi['low']:.2f}-{poi['high']:.2f} (fiyat içinde)")
    if conf["sweep"]:
        score += w.get("ltf_sweep", 2.0)
        confl.append(f"LTF {conf['sweep']['side']} sweep @ {conf['sweep']['ref']:.2f}")
    if conf["choch"]:
        score += w.get("ltf_choch", 1.5); confl.append(f"LTF CHoCH {conf['choch']}")
    if conf["fvg"]:
        score += w.get("ltf_fvg", 1.5)
        confl.append(f"LTF FVG entry {conf['fvg']['low']:.2f}-{conf['fvg']['high']:.2f}")
    if conf["ob"]:
        score += w.get("ltf_ob", 1.0)
        confl.append(f"LTF Order Block {conf['ob']['low']:.2f}-{conf['ob']['high']:.2f}")
    if conf["rb"]:
        score += w.get("ltf_rb", 1.5)
        confl.append(f"LTF Rejection Block {conf['rb']['low']:.2f}-{conf['rb']['high']:.2f} "
                     f"(likidite süpürme + fitil reddi, MT {conf['rb']['mt']:.2f})")
    if conf["bb"]:
        score += w.get("ltf_breaker", 1.5)
        confl.append(f"LTF Breaker Block {conf['bb']['low']:.2f}-{conf['bb']['high']:.2f} "
                     "(polarite döndü)")
    score = round(min(score, 10.0), 1)

    return {
        "engine": "MTF top-down (HTF bias → LTF entry)",
        "direction": bias,
        "entry": entry, "entry_mt": entry_mt, "sl": sl, "tp1": tp1, "tp2": tp2,
        "rr1": round(abs(tp1 - entry) / risk, 2),
        "rr2": round(abs(tp2 - entry) / risk, 2),
        "confidence": score,
        "atr": a,
        "kill_zone": kz,
        "trend": htf["trend"],
        "htf_zone": htf["zone"],
        "poi": poi,
        "liq_target": tp2 if tp2 == liq else htf["liq_target"],
        "confluences": confl,
        "reason": " + ".join(confl),
    }
