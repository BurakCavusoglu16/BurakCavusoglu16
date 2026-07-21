#!/usr/bin/env python3
"""Scalp sinyal botu — ana giriş noktası.

Akış:
  1) config.json'daki her enstrüman için OHLCV çek
  2) strategy.analyze ile scalp sinyali ara
  3) min_confidence üstündeki EN İYİ tek sinyali seç
  4) emir kartını üret; --dry-run değilse Telegram'a gönder

Kullanım:
  python bot.py --dry-run          # veri çeker, kartı ekrana basar, göndermez
  python bot.py                    # sinyal varsa Telegram'a gönderir
  python bot.py --self-test        # ağ olmadan sentetik veriyle mantığı doğrular

Eğitim/simülasyon amaçlıdır — yatırım tavsiyesi değildir. Gerçek emir açmaz;
sadece demo/paper hesapta elle denemen için kart üretir.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import strategy as strat
from data import fetch_ohlcv
from notify import send_telegram

HERE = os.path.dirname(os.path.abspath(__file__))
TR = timezone(timedelta(hours=3))


def load_config(path=None):
    path = path or os.path.join(HERE, "config.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fmt(x, digits):
    return f"{x:,.{digits}f}"


def build_card(inst, sig, now_tr):
    """Görseldeki emir kartı formatında Telegram (HTML) metni üretir."""
    d = inst["digits"]
    pip = inst["pip"]
    arrow = "🟢 LONG" if sig["direction"] == "LONG" else "🔴 SHORT"
    risk = abs(sig["entry"] - sig["sl"])
    return (
        f"🎯 <b>EMİR KARTI — {inst['name']} {sig['direction']}</b> (5dk scalp, {now_tr:%H:%M} TR)\n"
        f"\n"
        f"{arrow} — <b>Giriş ~{fmt(sig['entry'], d)}</b>\n"
        f"🛑 SL: {fmt(sig['sl'], d)}  (risk ~{fmt(risk, d)} {pip})\n"
        f"✅ TP1: {fmt(sig['tp1'], d)}  (R:R {sig['rr1']}) → yarıyı kapat, SL girişe\n"
        f"✅ TP2: {fmt(sig['tp2'], d)}  (R:R {sig['rr2']})\n"
        f"📐 GÜVEN: {sig['confidence']}/10 | RSI: {sig['rsi']} | ATR: {fmt(sig['atr'], d)}\n"
        f"\n"
        f"💬 <i>{sig['reason']}.</i>\n"
        f"⏩ KURALLAR: ① SL'e 1 mum kapanışı = çık. ② TP1'de yarı + SL girişe (risksiz). "
        f"③ Zıt yönde EMA9x21 kesişiminde erken çık.\n"
        f"\n"
        f"⚠️ <i>Simülasyon/eğitim amaçlıdır, yatırım tavsiyesi değildir. Demo hesapta dene.</i>"
    )


def scan(cfg):
    """Tüm enstrümanları tarar, (inst, sig) adaylarını döner."""
    candidates = []
    strat_cfg = cfg.get("strategy", {})
    for inst in cfg["instruments"]:
        try:
            candles = fetch_ohlcv(inst["yahoo"], cfg["interval"], cfg["range"])
        except Exception as e:  # noqa: BLE001 — veri hatası bir enstrümanı atlar, botu durdurmaz
            print(f"[uyarı] {inst['name']} verisi çekilemedi: {e}", file=sys.stderr)
            continue
        sig = strat.analyze(candles, strat_cfg)
        if sig:
            candidates.append((inst, sig))
            print(f"[sinyal] {inst['name']} {sig['direction']} güven {sig['confidence']}")
        else:
            print(f"[nötr]  {inst['name']} — sinyal yok")
    return candidates


def pick_best(candidates, min_conf):
    eligible = [(i, s) for i, s in candidates if s["confidence"] >= min_conf]
    if not eligible:
        return None
    return max(eligible, key=lambda x: x[1]["confidence"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="göndermeden ekrana bas")
    ap.add_argument("--self-test", action="store_true", help="sentetik veriyle mantığı doğrula")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    if args.self_test:
        return _self_test()

    cfg = load_config(args.config)
    now_tr = datetime.now(TR)
    candidates = scan(cfg)
    best = pick_best(candidates, cfg.get("min_confidence", 6.5))

    if not best:
        print("En uygun koşul yok — bu taramada emir kartı üretilmedi.")
        return 0

    inst, sig = best
    card = build_card(inst, sig, now_tr)
    if args.dry_run:
        print("\n----- EMİR KARTI (dry-run) -----")
        print(card)
        return 0

    ok = send_telegram(card)
    print("Telegram gönderildi." if ok else "Telegram gönderimi başarısız.")
    return 0 if ok else 1


def _self_test():
    """Ağ olmadan: pullback-devam kurulumu üret (uzun yükseliş + dip + son barda
    taze EMA9x21 yukarı kesişim), LONG sinyali bekle."""
    closes = []
    for i in range(220):
        closes.append(100 + i * 0.5)        # güçlü yükseliş -> EMA50>EMA200, fiyat üstte
    for i in range(30):
        closes.append(closes[-1] + 0.15)    # devam
    for i in range(5):
        closes.append(closes[-1] - 1.6)     # pullback -> EMA9 EMA21 altına
    for i in range(3):
        closes.append(closes[-1] + 3.6)     # toparlama -> son barda taze yukarı kesişim
    candles = []
    for i, c in enumerate(closes):
        candles.append({
            "t": 1_700_000_000 + i * 300,
            "o": c - 0.1, "h": c + 0.4, "l": c - 0.4, "c": c, "v": 1000,
        })
    sig = strat.analyze(candles, {})
    assert sig is not None, "self-test: sinyal beklenirken None döndü"
    assert sig["direction"] == "LONG", f"self-test: LONG beklendi, {sig['direction']} geldi"
    assert sig["rr1"] >= 1.4, f"self-test: R:R1 düşük ({sig['rr1']})"
    assert 0 <= sig["confidence"] <= 10
    print("self-test OK ->", {k: sig[k] for k in ("direction", "confidence", "rr1", "rr2", "rsi")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
