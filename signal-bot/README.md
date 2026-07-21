# Scalp Sinyal Botu (demo / eğitim)

Arka planda düzenli çalışan, US100 · GER40 · JPN225 · XAUUSD paritelerini 5 dakikalık
grafikte scalp mantığıyla tarayan ve **en uygun tek koşul** oluştuğunda Telegram'a
**emir kartı** gönderen bir bottur.

> ⚠️ Simülasyon/eğitim amaçlıdır, yatırım tavsiyesi değildir. Gerçek emir **açmaz** —
> sadece demo/paper hesapta elle denemen için kart üretir.

## Mimari — neden GitHub Actions?

"Sürekli açık" kısım GitHub Actions cron'unda yaşar (`.github/workflows/scalp-signals.yml`),
çünkü onu koşturduğun bulut geliştirme oturumu geçicidir (kapanır). Actions ise GitHub'ın
sunucularında, sen bir şey açık tutmadan çalışır.

```
GitHub Actions (cron, 5 dk)  ->  bot.py  ->  Yahoo OHLCV çek
                                      |
                                strategy.analyze  (EMA9x21 kesişim + EMA50/200 bias + RSI + ATR)
                                      |
                          en iyi tek sinyal (güven >= eşik)
                                      |
                             notify.send_telegram  ->  Telegram
```

## Strateji (5dk scalp)

| Bileşen | Kural |
|---|---|
| Trend bias | EMA50 vs EMA200 + fiyatın EMA50'ye konumu |
| Giriş tetiği | EMA9 × EMA21 **taze** kesişim (son kapanan mumda) |
| Momentum filtresi | RSI14 aşırı bölgede değil |
| SL / TP | ATR14 tabanlı: SL 1.0×ATR, TP1 1.5×ATR, TP2 2.5×ATR |
| Seçim | Eşik üstü sinyaller içinden **en yüksek güvenli tek** enstrüman |

Tüm eşikler `config.json` içinde; kod tarafında sihirli sabit yok.

## Kurulum (canlı hale getirmek için 3 adım)

1. **Telegram botu:** Telegram'da `@BotFather` → `/newbot` → token'ı al.
   Chat id için botuna bir mesaj at, sonra
   `https://api.telegram.org/bot<TOKEN>/getUpdates` adresinden `chat.id`'yi oku.
2. **Secrets ekle:** Depoda **Settings → Secrets and variables → Actions → New repository secret**:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. **Merge et:** Bu dal `main`'e merge edilince cron aktifleşir. Beklemeden test için
   **Actions → Scalp Sinyal Botu → Run workflow** (workflow_dispatch).

## Yerel kullanım

```bash
cd signal-bot
python bot.py --self-test     # ağsız: strateji mantığını doğrular
python bot.py --dry-run       # veri çeker, kartı ekrana basar (göndermez)
python bot.py                 # sinyal varsa Telegram'a gönderir (env secrets gerekir)
```

Ayar için `config.json` (enstrümanlar, `interval`, `min_confidence`, ATR çarpanları).

## Dürüst sınırlar

- **GitHub cron gerçek scalp için yavaş/kaba:** en az 5 dk aralık, yoğunlukta gecikebilir
  ve nadiren atlanabilir. Düşük gecikmeli gerçek scalp istersen botu kendi
  daima-açık makinende/VPS'inde `while`/systemd-timer ile koştur.
- **Veri kaynağı Yahoo** (ücretsiz, gecikmeli olabilir). Gerçek zamanlı TradingView verisi
  istersen, ayrı kurduğumuz TradingView MCP'yi **kendi PC'nde** TradingView Desktop açıkken
  kullanman gerekir (bu bulut ortamında masaüstü uygulaması olmadığı için bağlanamaz).
- **Otomatik emir yok:** bot bilinçli olarak yalnızca bildirim üretir; işlemi demo hesabında
  sen açarsın.
