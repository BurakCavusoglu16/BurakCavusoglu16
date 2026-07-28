# TradingView MCP — kurulum durumu ve doğru kullanım

İstediğin kurulum adımları uygulandı ama **bu bulut ortamında çalışamaz**; sebebi ve
kendi makinende nasıl çalıştıracağın aşağıda.

## Bu oturumda yapılanlar

- `git clone https://github.com/tradesdontlie/tradingview-mcp.git` ✅
- `npm install` ✅ (bağımlılıklar kuruldu)
- `~/.claude/.mcp.json` içine `tradingview` sunucusu eklendi ✅
- `tv status` (= `tv_health_check` karşılığı) → ❌ `CDP connection failed`
- `tv launch` → ❌ `TradingView not found on linux`

## Neden burada bağlanamıyor?

Bu MCP, senin makinende çalışan **TradingView Desktop** uygulamasına Chrome DevTools
Protocol (debug portu 9222) üzerinden bağlanır. Burası başsız (headless) ve **geçici** bir
bulut container'ı: ne TradingView Desktop kurulu, ne de oturum sürekli açık kalıyor.
Yani `~/.claude/.mcp.json` de dahil buradaki her şey oturum kapanınca kaybolur.

## Kendi PC'nde çalıştırmak için

1. TradingView Desktop'ı kur ve geçerli aboneliğinle giriş yap.
2. Depoyu klonla, kur:
   ```bash
   git clone https://github.com/tradesdontlie/tradingview-mcp.git ~/tradingview-mcp
   cd ~/tradingview-mcp && npm install
   ```
3. Claude Code MCP config'ine ekle (`~/.claude/.mcp.json`):
   ```json
   {
     "mcpServers": {
       "tradingview": {
         "command": "node",
         "args": ["/ABSOLUTE/PATH/tradingview-mcp/src/server.js"]
       }
     }
   }
   ```
4. TradingView'ı debug portuyla başlat (MCP'nin `tv_launch` aracı ya da elle):
   - Windows: depodaki `scripts\launch_tv_debug.bat`
   - Mac: `/Applications/TradingView.app/Contents/MacOS/TradingView --remote-debugging-port=9222`
5. Bağlantıyı doğrula: `tv_health_check` (CLI'da `tv status`).

## Bu botla ilişkisi

Bu depodaki scalp sinyal botu TradingView MCP'ye **bağımlı değildir** — verisini Yahoo'dan
çeker, böylece GitHub Actions'ta sensiz de koşar. TradingView MCP'yi ancak kendi makinende
gerçek zamanlı grafik verisi/analizi için ayrıca kullanırsın; ikisi bağımsız çalışır.
