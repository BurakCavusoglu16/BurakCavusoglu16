#!/usr/bin/env python3
"""Scalp sinyal botu — ICT/SMC motoru + Forex Factory haber filtresi.

Akış:
  1) config.json'daki her enstrüman için OHLCV çek (5dk)
  2) Forex Factory: yüksek etkili haber penceresindeyse enstrümanı ATLA (blackout)
  3) smc.analyze_smc: likidite sweep + BOS/CHoCH + displacement + FVG/IFVG + OB + KillZone
  4) min_confidence üstündeki EN İYİ tek sinyali seç
  5) zengin emir kartını üret; --dry-run değilse Telegram'a gönder

Kullanım:
  python bot.py --self-test    # ağsız: SMC mantığını doğrular
  python bot.py --dry-run      # veri çeker, kartı ekrana basar (göndermez)
  python bot.py                # sinyal varsa Telegram'a gönderir

Eğitim/simülasyon amaçlıdır — yatırım tavsiyesi değildir. Gerçek emir açmaz.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import smc
from data import fetch_ohlcv
from notify import send_telegram
from news import news_verdict, fetch_calendar

HERE = os.path.dirname(os.path.abspath(__file__))
TR = timezone(timedelta(hours=3))


def load_config(path=None):
    path = path or os.path.join(HERE, "config.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fmt(x, digits):
    return f"{x:,.{digits}f}" if x is not None else "—"


def build_card(inst, sig, now_tr, news_warn=None):
    """Zengin ICT/SMC emir kartı (Telegram HTML)."""
    d = inst["digits"]
    pip = inst["pip"]
    arrow = "🟢 LONG" if sig["direction"] == "LONG" else "🔴 SHORT"
    risk = abs(sig["entry"] - sig["sl"])
    conf_lines = "\n".join(f"   • {c}" for c in sig["confluences"])
    kz = sig.get("kill_zone") or "seans dışı"
    lines = [
        f"🎯 <b>EMİR KARTI — {inst['name']} {sig['direction']}</b>  ({inst_engine(sig)}, {now_tr:%H:%M} TR)",
        "",
        f"{arrow} — <b>Giriş ~{fmt(sig['entry'], d)}</b>",
        f"🛑 SL: {fmt(sig['sl'], d)}   (risk ~{fmt(risk, d)} {pip})",
        f"✅ TP1: {fmt(sig['tp1'], d)}   (R:R {sig['rr1']}) → yarıyı kapat, SL girişe",
        f"✅ TP2: {fmt(sig['tp2'], d)}   (R:R {sig['rr2']})",
        f"📐 GÜVEN: {sig['confidence']}/10 | Trend: {sig['trend']} | KillZone: {kz}"
        + (f" | RSI: {sig['rsi']}" if sig.get("rsi") is not None else ""),
    ]
    if sig.get("liq_target") is not None:
        lines.append(f"🎯 Hedef likidite: ~{fmt(sig['liq_target'], d)}")
    lines += [
        "",
        "🧩 <b>Confluence (ICT/SMC):</b>",
        conf_lines,
    ]
    if news_warn:
        lines += ["", news_warn]
    lines += [
        "",
        "⏩ KURALLAR: ① SL'e 1 mum kapanışı = çık. ② TP1'de yarı + SL girişe (risksiz). "
        "③ Zıt yönde likidite sweep/CHoCH görürsen erken çık.",
        "",
        "⚠️ <i>Simülasyon/eğitim amaçlıdır, yatırım tavsiyesi değildir. Demo hesapta dene.</i>",
    ]
    return "\n".join(lines)


def inst_engine(sig):
    return sig.get("engine", "5dk scalp")


def scan(cfg, now_utc, events):
    """Tüm enstrümanları tarar; blackout'ları atlar. (inst, sig, warn) adayları döner."""
    candidates = []
    smc_cfg = cfg.get("smc", {})
    for inst in cfg["instruments"]:
        nv = news_verdict(inst["name"], now_utc, cfg, events)
        if nv["blackout"]:
            print(f"[haber]  {inst['name']} — blackout, atlandı ({nv['warn']})")
            continue
        try:
            candles = fetch_ohlcv(inst["yahoo"], cfg["interval"], cfg["range"])
        except Exception as e:  # noqa: BLE001
            print(f"[uyarı] {inst['name']} verisi çekilemedi: {e}", file=sys.stderr)
            continue
        sig = smc.analyze_smc(candles, now_utc, smc_cfg)
        if sig:
            candidates.append((inst, sig, nv["warn"]))
            print(f"[sinyal] {inst['name']} {sig['direction']} güven {sig['confidence']} "
                  f"| {', '.join(sig['confluences'][:3])}")
        else:
            print(f"[nötr]  {inst['name']} — SMC confluence yetersiz")
    return candidates


def pick_best(candidates, min_conf):
    eligible = [c for c in candidates if c[1]["confidence"] >= min_conf]
    if not eligible:
        return None
    return max(eligible, key=lambda x: x[1]["confidence"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    if args.self_test:
        return _self_test()

    cfg = load_config(args.config)
    now_utc = datetime.now(timezone.utc)
    now_tr = now_utc.astimezone(TR)

    # Haber takvimini bir kez çek (hepsi için ortak); erişilemezse boş -> filtre pasifleşir
    try:
        events = fetch_calendar()
    except Exception as e:  # noqa: BLE001
        print(f"[haber]  takvim çekilemedi, haber filtresi pasif: {e}", file=sys.stderr)
        events = []

    candidates = scan(cfg, now_utc, events)
    best = pick_best(candidates, cfg.get("min_confidence", 6.5))
    if not best:
        print("En uygun koşul yok — bu taramada emir kartı üretilmedi.")
        return 0

    inst, sig, warn = best
    card = build_card(inst, sig, now_tr, warn)
    if args.dry_run:
        print("\n----- EMİR KARTI (dry-run) -----")
        print(card)
        return 0

    ok = send_telegram(card)
    print("Telegram gönderildi." if ok else "Telegram gönderimi başarısız.")
    return 0 if ok else 1


def _self_test():
    """Ağsız uçtan uca: SMC dedektör testlerini çalıştır + kart üret."""
    import test_smc
    test_smc.run()
    cs = test_smc._build_long_scenario()
    t = datetime(2026, 7, 21, 8, 30, tzinfo=timezone.utc)
    cfg = load_config()
    sig = smc.analyze_smc(cs, t, cfg["smc"])
    assert sig and sig["direction"] == "LONG"
    card = build_card({"name": "US100", "digits": 1, "pip": "puan"},
                      sig, t.astimezone(TR),
                      "⚠️ 45 dk sonra USD yüksek etkili haber: örnek — TP/SL sıkı tut")
    print("\n----- ÖRNEK KART -----")
    print(card)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
