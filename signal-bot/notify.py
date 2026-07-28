"""Telegram bildirimi — saf stdlib HTTPS POST.

Gerekli ortam değişkenleri (GitHub Actions secrets olarak ekle):
  TELEGRAM_BOT_TOKEN  — @BotFather'dan aldığın bot token'ı
  TELEGRAM_CHAT_ID    — mesajın gideceği sohbet/kanal id'si
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error


def send_telegram(text, token=None, chat_id=None, timeout=15):
    """Telegram'a mesaj gönderir. Başarıda True döner.

    token/chat_id verilmezse ortam değişkenlerinden okunur.
    """
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID tanımlı değil "
            "(GitHub Actions secrets veya ortam değişkeni olarak ekle)."
        )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.load(resp)
            return bool(body.get("ok"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Telegram HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}")
