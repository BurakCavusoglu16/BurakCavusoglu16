"""SMC dedektörleri için birim testleri — ağsız, sentetik OHLCV ile.

Çalıştır: python test_smc.py   (hepsi geçerse 'ALL SMC TESTS OK')
"""
from datetime import datetime, timezone, timedelta
import smc


def C(o, h, low, c):
    return {"t": 0, "o": o, "h": h, "l": low, "c": c, "v": 1000}


def test_swings():
    # basit zigzag: tepe @2, dip @5
    cs = [C(10, 11, 9, 10), C(11, 13, 10, 12), C(12, 16, 11, 15),
          C(15, 15, 12, 13), C(13, 13, 10, 11), C(11, 11, 7, 8),
          C(8, 12, 8, 11), C(11, 14, 10, 13)]
    sh, sl = smc.swing_points(cs, k=2)
    assert 2 in sh, f"tepe @2 bulunmalı, {sh}"
    assert 5 in sl, f"dip @5 bulunmalı, {sl}"


def test_fvg_bull():
    # boğa FVG: mum[i-1].high < mum[i+1].low
    cs = [C(10, 11, 9, 10),          # i-1  high=11
          C(11, 16, 11, 15),         # i    büyük impuls
          C(15, 17, 12.5, 16)]       # i+1  low=12.5 > 11 -> gap [11,12.5]
    fvgs = smc.find_fvgs(cs)
    assert any(f["type"] == "bull" and f["low"] == 11 and f["high"] == 12.5 for f in fvgs), fvgs


def test_fvg_bear():
    cs = [C(20, 21, 19, 19.5),       # i-1 low=19
          C(19.5, 19.5, 14, 15),     # i impuls aşağı
          C(15, 18, 14, 17)]         # i+1 high=18 < 19 -> gap [18,19]
    fvgs = smc.find_fvgs(cs)
    assert any(f["type"] == "bear" and f["low"] == 18 and f["high"] == 19 for f in fvgs), fvgs


def test_liquidity_sweep_ssl():
    # önce net swing low kur (dip @2), sonra altını süpürüp üstünde kapat
    cs = [C(20, 21, 19, 20), C(20, 20, 18, 19),
          C(19, 19, 15, 16),               # dip @2 (low=15)
          C(16, 18, 16, 17), C(17, 19, 16, 18),
          C(18, 19, 17, 18), C(18, 19, 17, 18),   # araya normal barlar (swing dip teyidi)
          C(18, 18, 14.5, 17)]             # süpürme: low=14.5<15, close=17>15
    sw = smc.liquidity_sweep(cs, k=2, lookback=12)
    assert sw and sw["side"] == "SSL", f"SSL sweep beklendi: {sw}"
    assert abs(sw["ref"] - 15) < 1e-9 and sw["extreme"] == 14.5


def test_displacement():
    cs = [C(10, 10.2, 9.8, 10)] * 20
    cs = [dict(x) for x in cs]
    cs.append(C(10, 13.5, 10, 13.4))  # büyük gövde
    a = smc.atr(cs, 14)
    d = smc.displacement(cs, a, mult=1.5, lookback=3)
    assert d and d["direction"] == "up", f"displacement up beklendi: {d}"


def test_rejection_block_bull():
    """Swing dibinde uzun alt fitilli mum -> bullish RB [fitil dibi, gövde dibi]."""
    cs = [C(20, 21, 19, 20), C(20, 20, 18, 19),
          C(16.5, 17, 12, 16.4),            # pin bar: alt fitil 4.4 >> gövde 0.1
          C(16.4, 18, 16, 17.5), C(17.5, 19, 17, 18.5),
          C(18.5, 19, 17.5, 18), C(18, 19, 17.5, 18.5)]
    rb = smc.rejection_block(cs, "LONG", k=2, lookback=20, wick_ratio=1.0)
    assert rb and abs(rb["low"] - 12) < 1e-9 and abs(rb["high"] - 16.4) < 1e-9, rb


def test_rejection_block_bear():
    """Swing tepesinde uzun üst fitilli mum -> bearish RB [gövde tepesi, fitil tepesi]."""
    cs = [C(10, 11, 9, 10), C(11, 12, 10, 11.5),
          C(12, 18, 11.8, 12.2),            # üst fitil 5.8 >> gövde 0.2
          C(12.2, 13, 11, 11.5), C(11.5, 12, 10, 10.5),
          C(10.5, 11, 10, 10.2), C(10.2, 11, 9.8, 10)]
    rb = smc.rejection_block(cs, "SHORT", k=2, lookback=20, wick_ratio=1.0)
    assert rb and abs(rb["low"] - 12.2) < 1e-9 and abs(rb["high"] - 18) < 1e-9, rb


def test_rejection_block_filter():
    """Dev gövde + minik fitil RB SAYILMAZ (belirginlik filtresi)."""
    cs = [C(20, 21, 19, 20), C(20, 20, 18, 19),
          C(17, 17.1, 13, 13.1),
          C(13.1, 15, 13, 14.5), C(14.5, 16, 14, 15.5),
          C(15.5, 16, 15, 15.8), C(15.8, 16.5, 15.5, 16)]
    assert smc.rejection_block(cs, "LONG", 2, 20, 1.0) is None


def test_kill_zone():
    windows = [[420, 600, "Londra"], [750, 930, "NewYork"]]
    t = datetime(2026, 7, 21, 8, 30, tzinfo=timezone.utc)  # 08:30 = 510 dk
    assert smc.in_kill_zone(t, windows) == "Londra"
    t2 = datetime(2026, 7, 21, 3, 0, tzinfo=timezone.utc)
    assert smc.in_kill_zone(t2, windows) is None


def _build_long_scenario():
    """Aşağı trend -> SSL süpürme -> yukarı displacement + BOS -> LONG confluence."""
    cs = []
    p = 100.0
    # düşüş trendi (lower highs/lows) — swing yapısı kursun (>=80 mum toplam)
    for i in range(75):
        p -= 0.4
        wig = 0.6 if i % 4 else -0.6
        cs.append(C(p + 0.2, p + 0.5 + max(0, wig), p - 0.5 + min(0, wig), p))
    # belirgin bir swing low bırak
    for i in range(6):
        p += 0.2
        cs.append(C(p - 0.2, p + 0.4, p - 0.4, p))
    swing_low_price = min(c["l"] for c in cs[-30:])
    # SSL süpürme mumu: swing low altına fitil, üstünde kapat
    cs.append(C(p, p + 0.3, swing_low_price - 1.5, p + 0.2))
    # güçlü yukarı displacement (FVG + BOS yaratır)
    base = cs[-1]["c"]
    cs.append(C(base, base + 4.0, base - 0.2, base + 3.8))
    cs.append(C(base + 3.8, base + 6.5, base + 3.6, base + 6.2))  # gap: [base+? ] FVG
    cs.append(C(base + 6.2, base + 7.0, base + 5.5, base + 6.0))  # geri çekilme (FVG'ye dönüş)
    return cs


def test_full_long_signal():
    cs = _build_long_scenario()
    t = datetime(2026, 7, 21, 8, 30, tzinfo=timezone.utc)
    cfg = {
        "min_bars": 60, "swing_k": 2,
        "kill_zones": [[420, 600, "Londra KZ"]],
        "weights": {"kill_zone": 2.0, "sweep": 2.5, "structure": 2.0,
                     "displacement": 1.0, "fvg": 2.0, "ifvg": 1.5,
                     "order_block": 1.5, "rsi": 0.5},
    }
    sig = smc.analyze_smc(cs, t, cfg)
    assert sig is not None, "LONG sinyal bekleniyordu, None döndü"
    assert sig["direction"] == "LONG", sig["direction"]
    assert sig["confidence"] >= 5.0, f"güven düşük: {sig['confidence']}"
    assert sig["sl"] < sig["entry"] < sig["tp1"] < sig["tp2"], "SL/TP sıralaması bozuk"
    assert sig["rr1"] >= 1.4 and sig["rr2"] >= 2.4, (sig["rr1"], sig["rr2"])
    assert any("sweep" in x.lower() or "süpür" in x.lower() for x in sig["confluences"]), sig["confluences"]
    return sig


def run():
    test_swings()
    test_fvg_bull()
    test_fvg_bear()
    test_liquidity_sweep_ssl()
    test_displacement()
    test_rejection_block_bull()
    test_rejection_block_bear()
    test_rejection_block_filter()
    test_kill_zone()
    sig = test_full_long_signal()
    print("ALL SMC TESTS OK")
    print("örnek sinyal:", {k: sig[k] for k in
          ("direction", "confidence", "rr1", "rr2", "kill_zone", "trend")})
    print("confluences:", sig["confluences"])


if __name__ == "__main__":
    run()
