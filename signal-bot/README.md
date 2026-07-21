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

## İş akışı — Çok Zaman Dilimli (MTF) top-down (`mtf.py`)

Gerçek trader mantığı: **önce büyük resim, sonra detay.**

```
HTF (1h)  →  BIAS: yapısal yön (HH/LL) + premium/discount + POI (FVG / Order Block)
                 │
                 ▼   fiyat, bias yönündeki bir HTF POI'sine geldi mi? (discount'ta)
LTF (5m)  →  ONAY: likidite sweep + CHoCH + FVG entry  →  ENTRY / SL / TP
```

- **Sinyal ancak üç koşul hizalanınca üretilir:** (1) net HTF bias, (2) fiyat bias yönünde
  bir HTF POI'sinin **içinde** ve doğru **discount/premium** bölgesinde, (3) LTF'de teyit
  (sweep veya CHoCH). Alan oluşmadan ya da onay gelmeden **bekler** — tıpkı bir trader gibi.
- **SL** LTF sweep/POI ötesinde (yapısal), **TP2** HTF likidite hedefinde.
- Zaman dilimleri `config.json > mtf` (`htf_interval`, `ltf_interval`) ile ayarlanır.

## Alt katman — ICT / SMC dedektörleri (`smc.py`)

MTF motorunun kullandığı yapı taşları; her biri ayrı birim testiyle doğrulanmıştır
(`test_smc.py`, `test_mtf.py`).

| Bileşen | Ne yapar |
|---|---|
| **Market Structure** | Swing noktaları → BOS (Break of Structure) / CHoCH (Change of Character) |
| **Liquidity Sweep** | Swing dip/tepe altına-üstüne fitil + geri kapanış = stop avı ("Judas"). Birincil tetik. |
| **Displacement** | ATR'ye göre güçlü impuls mumu (kurumsal niyet) |
| **FVG** | 3-mum Fair Value Gap (imbalance) = giriş bölgesi |
| **IFVG** | İhlal edilip polaritesi dönen FVG (inverse) = destek/direnç |
| **Order Block** | İmpulstan önceki son zıt mum = giriş bölgesi |
| **Kill Zone** | Asya / Londra / New York / Londra Kapanış zaman pencereleri (UTC) |
| **Forex Factory** | Yüksek etkili haber ±30 dk → **blackout** (işlem yok); yaklaşan haber → karta uyarı |

**Skor:** confluence ağırlıkları toplanır (`config.json > mtf.weights`), `min_confidence`
üstündeki **en yüksek güvenli tek** enstrüman kart olur.

Kill zone'lar UTC dakika cinsinden (`config.json > mtf.kill_zones`). Örn. Londra KZ
`[420,600]` = 07:00–10:00 UTC = **10:00–13:00 TR**; New York KZ `[750,930]` = **15:30–18:30 TR**.

Tüm eşikler `config.json` içinde; kodda sihirli sabit yok.

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
python bot.py --self-test     # ağsız: tüm SMC dedektörlerini test eder + örnek kart basar
python test_smc.py            # sadece SMC birim testleri
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
