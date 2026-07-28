#!/usr/bin/env python3
"""MTF/ICT stratejisi için walk-forward backtest.

Her LTF barında, YALNIZCA o bara kadarki veriyi kullanarak (lookahead yok)
mtf.analyze_mtf çalıştırır; sinyal varsa işlemi açar ve sonraki barlarda
SL/TP kontrolüyle yönetir.

İşlem yönetimi (emir kartındaki kurallarla birebir):
  - Giriş: sinyal barının kapanışı (market). RB Mean Threshold varsa limit
    modu (--entry mt) ile MT'ye çekilir; N bar içinde dolmazsa iptal.
  - TP1'de pozisyonun yarısı kapanır ve SL girişe çekilir (risksiz).
  - Kalan yarı TP2'de kapanır ya da SL/başabaş'ta çıkar.
  - Aynı anda tek pozisyon.

Sonuç: işlem sayısı, kazanma oranı, profit factor, ortalama R, beklenti,
maksimum drawdown (R cinsinden) ve tam işlem listesi.

Kullanım:
  python backtest.py --symbol US100 --htf 1h --ltf 5m --range 60d
  python backtest.py --all --range 60d --min-conf 6.0
  python backtest.py --self-test          # ağsız mantık doğrulaması

Eğitim/simülasyon amaçlıdır; geçmiş performans gelecek getiri garantisi değildir.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import mtf
from data import fetch_ohlcv

HERE = os.path.dirname(os.path.abspath(__file__))


def load_config(path=None):
    with open(path or os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def _htf_slice(htf, ts, window=400, _ts_cache={}):
    """HTF mumlarından zamanı ts'i AŞMAYAN son 'window' tanesini döner.

    Lookahead engeli + performans: her barda tüm geçmişi taramak O(n²) yapıyordu;
    bisect ile kesip kayan pencere kullanıyoruz. Strateji zaten son ~60 bara bakar,
    bu yüzden sonuç değişmez, süre lineerleşir.
    """
    key = id(htf)
    times = _ts_cache.get(key)
    if times is None or len(times) != len(htf):
        times = [c["t"] for c in htf]
        _ts_cache[key] = times
    import bisect
    end = bisect.bisect_right(times, ts)
    return htf[max(0, end - window):end]


def simulate(htf, ltf, cfg, min_conf, entry_mode="market", limit_bars=12,
             warmup=250, max_hold=120, min_rr=0.0, max_per_day=None,
             kz_only=False, ltf_window=400):
    """Walk-forward simülasyon. (trades, stats) döner.

    Seçicilik filtreleri ("az işlem, yüksek R:R" hedefi için):
      min_rr      : TP2 R:R'ı bu değerin altındaki kurulumlar atlanır
      max_per_day : günlük işlem tavanı (ör. 3)
      kz_only     : sadece kill zone içindeki sinyaller alınır
    """
    m = cfg["mtf"]
    trades = []
    per_day = {}
    i = warmup
    n = len(ltf)

    while i < n - 1:
        bar = ltf[i]
        now_utc = datetime.fromtimestamp(bar["t"], tz=timezone.utc)
        hs = _htf_slice(htf, bar["t"])
        if len(hs) < m.get("htf", {}).get("min_bars", 60):
            i += 1
            continue

        # LTF'de de kayan pencere: strateji son ~60 bara bakar, 400 fazlasıyla yeter
        lo_i = max(0, i + 1 - ltf_window)
        sig = mtf.analyze_mtf(hs, ltf[lo_i: i + 1], now_utc, m)
        if not sig or sig["confidence"] < min_conf:
            i += 1
            continue
        # --- seçicilik filtreleri ---
        if min_rr > 0 and sig.get("rr2", 0) < min_rr:
            i += 1
            continue
        if kz_only and not sig.get("kill_zone"):
            i += 1
            continue
        day = now_utc.strftime("%Y-%m-%d")
        if max_per_day is not None and per_day.get(day, 0) >= max_per_day:
            i += 1
            continue

        direction = sig["direction"]
        sl, tp1, tp2 = sig["sl"], sig["tp1"], sig["tp2"]
        entry = sig["entry"]
        entry_i = i + 1  # bir sonraki barda icra (gerçekçi)

        # --- limit (Mean Threshold) modu: MT'ye çekilmeyi bekle ---
        if entry_mode == "mt" and sig.get("entry_mt"):
            target = sig["entry_mt"]
            filled = None
            for b in range(i + 1, min(i + 1 + limit_bars, n)):
                if direction == "LONG" and ltf[b]["l"] <= target:
                    filled = b
                    break
                if direction == "SHORT" and ltf[b]["h"] >= target:
                    filled = b
                    break
            if filled is None:
                i += 1
                continue  # limit dolmadı -> işlem yok
            entry, entry_i = target, filled

        risk = abs(entry - sl)
        if risk <= 0:
            i += 1
            continue

        # --- pozisyon yönetimi ---
        half_closed = False
        cur_sl = sl
        r_total = 0.0
        exit_i, exit_reason = None, None

        for b in range(entry_i, min(entry_i + max_hold, n)):
            hi, lo = ltf[b]["h"], ltf[b]["l"]
            if direction == "LONG":
                hit_sl = lo <= cur_sl
                hit_tp1 = hi >= tp1
                hit_tp2 = hi >= tp2
            else:
                hit_sl = hi >= cur_sl
                hit_tp1 = lo <= tp1
                hit_tp2 = lo <= tp2

            # Aynı barda hem SL hem TP varsa muhafazakâr davran: önce SL say.
            if hit_sl:
                r_here = (cur_sl - entry) / risk if direction == "LONG" else (entry - cur_sl) / risk
                r_total += r_here * (0.5 if half_closed else 1.0)
                exit_i, exit_reason = b, ("BE" if half_closed else "SL")
                break
            if not half_closed and hit_tp1:
                r_total += 0.5 * abs(tp1 - entry) / risk
                half_closed = True
                cur_sl = entry  # SL girişe -> risksiz
                if hit_tp2:
                    r_total += 0.5 * abs(tp2 - entry) / risk
                    exit_i, exit_reason = b, "TP2"
                    break
                continue
            if half_closed and hit_tp2:
                r_total += 0.5 * abs(tp2 - entry) / risk
                exit_i, exit_reason = b, "TP2"
                break

        if exit_i is None:  # süre doldu -> son fiyattan çık
            b = min(entry_i + max_hold, n) - 1
            px = ltf[b]["c"]
            r_here = (px - entry) / risk if direction == "LONG" else (entry - px) / risk
            r_total += r_here * (0.5 if half_closed else 1.0)
            exit_i, exit_reason = b, "TIME"

        per_day[day] = per_day.get(day, 0) + 1
        trades.append({
            "dir": direction, "entry": round(entry, 2), "sl": round(sl, 2),
            "tp1": round(tp1, 2), "tp2": round(tp2, 2),
            "conf": sig["confidence"], "kz": sig.get("kill_zone"),
            "R": round(r_total, 2), "reason": exit_reason,
            "t": datetime.fromtimestamp(ltf[entry_i]["t"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "bars": exit_i - entry_i,
        })
        i = exit_i + 1  # pozisyon kapanınca devam (aynı anda tek işlem)

    return trades, stats(trades)


def stats(trades, days=None):
    """İşlem listesinden performans metrikleri.

    days: veri kaç işlem gününü kapsıyor (günlük işlem sıklığı için).
    """
    if not trades:
        return {"trades": 0}
    rs = [t["R"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    # equity eğrisi -> max drawdown (R)
    eq, peak, mdd = 0.0, 0.0, 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    # işlem günü sayısı: verilmediyse işlemlerin benzersiz tarihlerinden tahmin
    if days is None:
        days = len({t["t"][:10] for t in trades if t.get("t")}) or 1
    return {
        "trades": len(rs),
        "per_day": round(len(rs) / max(days, 1), 2),
        "days": days,
        "win_rate": round(100.0 * len(wins) / len(rs), 1),
        "total_R": round(sum(rs), 2),
        "avg_R": round(sum(rs) / len(rs), 3),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "best_R": round(max(rs), 2),
        "worst_R": round(min(rs), 2),
        "max_dd_R": round(mdd, 2),
        "avg_bars": round(sum(t["bars"] for t in trades) / len(trades), 1),
    }


def print_report(name, st, trades, show=8):
    print(f"\n{'='*58}\n  {name}\n{'='*58}")
    if not st.get("trades"):
        print("  İşlem yok (sinyal üretilmedi ya da veri yetersiz).")
        return
    print(f"  İşlem sayısı   : {st['trades']}   ({st['per_day']} işlem/gün, {st['days']} gün)")
    print(f"  Kazanma oranı  : %{st['win_rate']}")
    print(f"  Toplam R       : {st['total_R']}")
    print(f"  Ortalama R     : {st['avg_R']}  (beklenti/işlem)")
    print(f"  Profit factor  : {st['profit_factor']}")
    print(f"  En iyi / kötü  : {st['best_R']} / {st['worst_R']}")
    print(f"  Max drawdown   : {st['max_dd_R']} R")
    print(f"  Ort. tutuş     : {st['avg_bars']} bar")
    print(f"\n  Son {min(show, len(trades))} işlem:")
    for t in trades[-show:]:
        print(f"    {t['t']}  {t['dir']:5s} @{t['entry']:>10}  "
              f"R={t['R']:>6}  {t['reason']:4s}  conf={t['conf']}  {t.get('kz') or '-'}")


def _self_test():
    """Ağsız: sentetik veriyle simülasyon mantığını doğrula."""
    import test_smc, test_mtf
    htf = test_mtf.build_htf_bullish()
    ltf = test_smc._build_long_scenario()
    cfg = load_config()
    # warmup'ı düşür ki sentetik seri işlem üretebilsin
    trades, st = simulate(htf, ltf, cfg, min_conf=0.0, warmup=len(ltf) - 6, max_hold=5)
    assert isinstance(trades, list), "trades listesi bekleniyordu"
    # R hesabı tutarlı mı: her işlemin R'si makul aralıkta
    for t in trades:
        assert -1.6 <= t["R"] <= 6.0, f"anormal R: {t}"
    # stats fonksiyonu boş listede patlamamalı
    assert stats([])["trades"] == 0
    demo = [{"R": 1.5, "bars": 3}, {"R": -1.0, "bars": 2}, {"R": 2.5, "bars": 5}]
    s = stats(demo)
    assert s["trades"] == 3 and s["win_rate"] == 66.7, s
    assert s["total_R"] == 3.0 and s["profit_factor"] == 4.0, s
    assert s["max_dd_R"] == -1.0, s
    print("backtest self-test OK ->", s)
    print(f"(sentetik seride {len(trades)} işlem simüle edildi)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=None, help="config'deki enstrüman adı (US100 vb.)")
    ap.add_argument("--all", action="store_true", help="tüm enstrümanlar")
    ap.add_argument("--htf", default=None)
    ap.add_argument("--ltf", default=None)
    ap.add_argument("--range", dest="rng", default="60d", help="LTF veri aralığı (60d, 1mo...)")
    ap.add_argument("--htf-range", default="2y")
    ap.add_argument("--min-conf", type=float, default=None)
    ap.add_argument("--entry", choices=["market", "mt"], default="market")
    ap.add_argument("--min-rr", type=float, default=0.0,
                    help="TP2 R:R alt sınırı (yüksek R:R seçiciliği)")
    ap.add_argument("--max-per-day", type=int, default=None,
                    help="günlük işlem tavanı (ör. 3)")
    ap.add_argument("--kz-only", action="store_true",
                    help="sadece kill zone içindeki sinyaller")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return _self_test()

    cfg = load_config()
    m = cfg["mtf"]
    htf_iv = args.htf or m["htf_interval"]
    ltf_iv = args.ltf or m["ltf_interval"]
    min_conf = args.min_conf if args.min_conf is not None else cfg.get("min_confidence", 7.0)

    insts = cfg["instruments"]
    if args.symbol:
        insts = [x for x in insts if x["name"].upper() == args.symbol.upper()]
        if not insts:
            print(f"Enstrüman bulunamadı: {args.symbol}", file=sys.stderr)
            return 1
    elif not args.all:
        insts = insts[:1]

    all_trades = []
    for inst in insts:
        try:
            htf = fetch_ohlcv(inst["yahoo"], htf_iv, args.htf_range)
            ltf = fetch_ohlcv(inst["yahoo"], ltf_iv, args.rng)
        except Exception as e:  # noqa: BLE001
            print(f"[uyarı] {inst['name']} verisi çekilemedi: {e}", file=sys.stderr)
            continue
        print(f"\n[{inst['name']}] HTF {htf_iv}: {len(htf)} bar | LTF {ltf_iv}: {len(ltf)} bar "
              f"| min_conf={min_conf} | giriş={args.entry} | min_rr={args.min_rr} "
              f"| max/gün={args.max_per_day} | kz_only={args.kz_only}")
        trades, st = simulate(htf, ltf, cfg, min_conf, entry_mode=args.entry,
                              min_rr=args.min_rr, max_per_day=args.max_per_day,
                              kz_only=args.kz_only)
        print_report(f"{inst['name']} — {ltf_iv} / {htf_iv}", st, trades)
        all_trades += trades

    if len(insts) > 1 and all_trades:
        print_report("TOPLAM (tüm enstrümanlar)", stats(all_trades), all_trades, show=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
