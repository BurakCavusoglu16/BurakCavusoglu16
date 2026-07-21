"""MTF top-down motoru için birim testleri — ağsız, sentetik HTF+LTF.

Çalıştır: python test_mtf.py
"""
from datetime import datetime, timezone
import mtf
import smc
import test_smc


def C(o, h, low, c):
    return {"t": 0, "o": o, "h": h, "l": low, "c": c, "v": 1000}


def build_htf_bullish():
    """Zigzag yükseliş (HH/HL) -> bullish FVG -> fiyat FVG'ye geri çekilir (discount)."""
    cs = []
    p = 100.0
    # zigzag yükseliş: her bacak +6 impuls, -2 pullback => HH + HL swing yapısı
    for leg in range(8):
        for _ in range(5):                     # impuls yukarı
            p += 1.2
            cs.append(C(p - 0.4, p + 0.7, p - 0.5, p + 0.3))
        for _ in range(3):                     # pullback (HL bırakır)
            p -= 0.7
            cs.append(C(p + 0.3, p + 0.5, p - 0.6, p))
    # bullish FVG yaratan impuls: A.high < C.low
    a = cs[-1]["c"]
    cs.append(C(a, a + 1.0, a - 1.0, a + 0.5))          # A  (high = a+1)
    cs.append(C(a + 0.5, a + 7.0, a + 0.4, a + 6.8))    # B  impuls
    cs.append(C(a + 6.8, a + 8.0, a + 3.0, a + 7.5))    # C  (low = a+3) -> FVG [a+1, a+3]
    # geri çekilme: fiyat FVG içine dönsün (~a+2), ama yapı bull kalsın
    for lvl in [a + 6.5, a + 5.0, a + 3.5, a + 2.5, a + 2.0]:
        cs.append(C(lvl + 0.3, lvl + 0.6, lvl - 0.5, lvl))
    return cs


def test_structural_bias_bull():
    cs = build_htf_bullish()
    assert smc.structural_bias(cs, 2) == "bull", "zigzag yükselişte bias bull olmalı"


def test_htf_bias_and_poi():
    cs = build_htf_bullish()
    hb = mtf.htf_bias(cs, {})
    assert hb["bias"] == "LONG", f"HTF bias LONG beklendi: {hb['bias']}"
    assert hb["active_poi"] is not None, "fiyat FVG POI'sinde olmalı (aktif POI None)"
    assert hb["active_poi"]["dir"] == "bull"
    return hb


def test_full_mtf_signal():
    htf = build_htf_bullish()
    ltf = test_smc._build_long_scenario()      # SSL sweep + displacement up + FVG + BOS
    now = datetime(2026, 7, 21, 8, 30, tzinfo=timezone.utc)  # Londra KZ
    cfg = {
        "htf": {"min_bars": 60, "swing_k": 2, "range_lookback": 60, "fvg_lookback": 40},
        "ltf": {"min_bars": 60, "swing_k": 2, "sweep_lookback": 12, "fvg_lookback": 30,
                 "sl_buffer_atr": 0.25},
        "kill_zones": [[420, 600, "Londra KZ"]],
        "weights": {"kill_zone": 1.5, "htf_bias": 2.0, "premium_discount": 1.5,
                     "htf_poi": 2.0, "ltf_sweep": 2.0, "ltf_choch": 1.5,
                     "ltf_fvg": 1.5, "ltf_ob": 1.0},
    }
    sig = mtf.analyze_mtf(htf, ltf, now, cfg)
    assert sig is not None, "MTF sinyal bekleniyordu, None döndü"
    assert sig["direction"] == "LONG", sig["direction"]
    assert sig["sl"] < sig["entry"] < sig["tp1"] <= sig["tp2"] or \
           sig["sl"] < sig["entry"] < sig["tp1"], "SL/TP sıralaması bozuk"
    assert sig["rr1"] >= 1.4, sig["rr1"]
    assert sig["confidence"] >= 6.0, f"güven düşük: {sig['confidence']}"
    assert any("HTF" in c for c in sig["confluences"]), sig["confluences"]
    assert any("LTF" in c for c in sig["confluences"]), sig["confluences"]
    return sig


def test_no_signal_without_poi():
    """Fiyat HTF POI'sinde değilken (alan oluşmadı) sinyal ÜRETMEMELİ."""
    htf = build_htf_bullish()
    # fiyatı POI'nin çok üstüne taşı (alan dışı) — son barları yukarı it
    a = htf[-1]["c"]
    for lvl in [a + 8, a + 9, a + 10]:
        htf.append(C(lvl - 0.3, lvl + 0.5, lvl - 0.5, lvl))
    ltf = test_smc._build_long_scenario()
    now = datetime(2026, 7, 21, 8, 30, tzinfo=timezone.utc)
    cfg = {"htf": {"min_bars": 60}, "ltf": {"min_bars": 60}, "kill_zones": [], "weights": {}}
    sig = mtf.analyze_mtf(htf, ltf, now, cfg)
    assert sig is None, "alan dışıyken sinyal üretilmemeli"


def run():
    test_structural_bias_bull()
    test_htf_bias_and_poi()
    test_no_signal_without_poi()
    sig = test_full_mtf_signal()
    print("ALL MTF TESTS OK")
    print("örnek MTF sinyal:", {k: sig[k] for k in
          ("direction", "confidence", "rr1", "rr2", "kill_zone", "htf_zone", "trend")})
    for c in sig["confluences"]:
        print("   •", c)


if __name__ == "__main__":
    run()
