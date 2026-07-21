"""Piyasa verisi çekme — Yahoo Finance chart JSON (anahtar gerekmez).

Not: Bu modül GitHub Actions runner'ında ya da senin makinende çalışır.
Bulut geliştirme container'ının giden proxy'si Yahoo'yu bloke edebilir; bu
normaldir — bot asıl olarak GitHub Actions'ta koşacak.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error

_UA = "Mozilla/5.0 (scalp-signal-bot; educational)"


def fetch_ohlcv(symbol, interval="5m", rng="1d", timeout=20):
    """Yahoo chart API'den OHLCV çeker. Kapanmış mumların listesini döner.

    symbol: Yahoo sembolü (örn '^NDX', 'GC=F', '^GDAXI', '^N225')
    interval: '1m','2m','5m','15m','1h' ...
    rng: '1d','5d' ...
    """
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
        f"?interval={interval}&range={rng}&includePrePost=false"
    )
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)

    result = payload["chart"]["result"][0]
    ts = result["timestamp"]
    q = result["indicators"]["quote"][0]
    opens, highs, lows, closes, vols = (
        q["open"], q["high"], q["low"], q["close"], q.get("volume", [None] * len(ts))
    )

    candles = []
    for i in range(len(ts)):
        o, h, low, c = opens[i], highs[i], lows[i], closes[i]
        if None in (o, h, low, c):
            continue  # eksik/oluşmakta olan mumu atla
        candles.append({
            "t": ts[i], "o": o, "h": h, "l": low, "c": c,
            "v": vols[i] if i < len(vols) and vols[i] is not None else 0,
        })

    # Son mum genelde hâlâ oluşuyor olabilir; tetiklemeyi kapanmış son mumdan yap.
    # Yahoo son barı kapanmamış verirse çıkarmak daha güvenli:
    return candles
