"""Forex Factory haber filtresi — haftalık takvim JSON'u.

Yüksek etkili (red folder) haber penceresinde işlem açmayı engeller ("news blackout"),
yaklaşan haberi karta uyarı olarak ekler. Bu, ICT mantığında da kritik: yüksek etkili
haber anında likidite/volatilite manipülatiftir, teknik kurulum güvenilmez.

Endpoint (anahtarsız, ForexFactory türevi): nfs.faireconomy.media/ff_calendar_thisweek.json
GitHub Actions runner'ında çalışır; bulut geliştirme proxy'si erişimi engelleyebilir.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_UA = "Mozilla/5.0 (scalp-signal-bot; educational)"

# Enstrüman -> ilgili para birimi/birimleri
INSTRUMENT_CCY = {
    "US100": ["USD"],
    "GER40": ["EUR"],
    "JPN225": ["JPY"],
    "XAUUSD": ["USD"],   # altın birincil olarak USD/DXY ile sürülür
}


def _parse_dt(s):
    """FF tarih string'ini timezone-aware UTC datetime'a çevirir."""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fetch_calendar(timeout=20):
    """Haftalık takvimi çeker, normalize edilmiş event listesi döner.
    Her event: {ccy, impact, title, dt(UTC)}."""
    req = urllib.request.Request(_URL, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = json.load(resp)

    events = []
    for e in raw:
        ccy = e.get("country") or e.get("currency") or ""
        impact = (e.get("impact") or e.get("impactTitle") or "").capitalize()
        dt = _parse_dt(e.get("date") or e.get("dateline") or "")
        if not ccy or dt is None:
            continue
        events.append({
            "ccy": ccy.upper(),
            "impact": impact,          # High / Medium / Low / Holiday
            "title": e.get("title", ""),
            "dt": dt,
        })
    return events


def news_verdict(instrument_name, now_utc, cfg, events=None):
    """Bir enstrüman için haber durumunu değerlendirir.

    Döner: {
      'blackout': bool,      # yüksek etkili habere çok yakın -> işlem açma
      'warn': str|None,      # yaklaşan haber uyarısı (karta eklenir)
      'available': bool,     # takvim çekilebildi mi
    }
    """
    ccys = INSTRUMENT_CCY.get(instrument_name, [])
    blackout_min = cfg.get("news_blackout_min", 30)   # ±30 dk kesin engel
    warn_min = cfg.get("news_warn_min", 90)           # 90 dk içinde uyar

    if events is None:
        try:
            events = fetch_calendar()
        except Exception:  # noqa: BLE001 — haber çekilemezse engellemeyip not düş
            return {"blackout": False, "warn": None, "available": False}

    relevant = [e for e in events
                if e["ccy"] in ccys and e["impact"] == "High"]
    blackout = False
    warn = None
    soonest = None
    for e in relevant:
        delta_min = (e["dt"] - now_utc).total_seconds() / 60.0
        if -blackout_min <= delta_min <= blackout_min:
            blackout = True
            warn = f"⛔ {e['ccy']} yüksek etkili haber ŞİMDİ ({e['title']}) — işlem yok"
            break
        if 0 < delta_min <= warn_min:
            if soonest is None or delta_min < soonest[0]:
                soonest = (delta_min, e)
    if not blackout and soonest:
        d, e = soonest
        warn = f"⚠️ {int(d)} dk sonra {e['ccy']} yüksek etkili haber: {e['title']} — TP/SL sıkı tut"
    return {"blackout": blackout, "warn": warn, "available": True}
