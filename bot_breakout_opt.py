import pandas as pd, numpy as np, ccxt, time, math, requests, os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Cargar variables .env
load_dotenv()
API_KEY = os.getenv("BINANCE_KEY")
API_SECRET = os.getenv("BINANCE_SECRET")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Configuración del bot
symbol = "AEUR/USDT"
DONCHIAN_N = 10
STOP_MULT   = 2.0
TP_MULT     = 1.26
RISK_PCT    = 0.029
SLIPPAGE    = 0.0002
FEE         = 0.001
capital = 280
profit_24h = 0
last_report_time = datetime.now()

# Inicializar Binance
exchange = ccxt.binance({
    "apiKey": API_KEY,
    "secret": API_SECRET,
    "enableRateLimit": True,
    "options": {"defaultType": "spot"}
})

def send_telegram(message):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("[ERROR] Telegram no configurado.")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = {"chat_id": TG_CHAT_ID, "text": message}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("[Telegram error]", e)

def fetch_ohlcv():
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1m', limit=DONCHIAN_N + 2)
    df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df

def compute_atr(df, period=14):
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift()).abs(),
        (df['low'] - df['close'].shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def run_bot():
    global capital, profit_24h, last_report_time
    position = 0
    entry_price = stop_price = target_price = 0
    base_asset = symbol.split("/")[0]

    send_telegram("🤖 Bot REAL AEUR/USDT iniciado ✅")

    while True:
        try:
            df = fetch_ohlcv()
            df['ATR'] = compute_atr(df)

            last = df.iloc[-1]
            high_channel = df['high'].rolling(DONCHIAN_N).max().iloc[-2]
            now = datetime.now()
            now_str = now.strftime('%Y-%m-%d %H:%M:%S')

            price_now = last['close']

            if position == 0:
                if last['high'] > high_channel and not math.isnan(last['ATR']):
                    risk_usd = capital * RISK_PCT
                    qty = risk_usd / price_now
                    entry_price = price_now * (1 + SLIPPAGE)
                    stop_price  = entry_price - STOP_MULT * last['ATR']
                    target_price= entry_price + TP_MULT * last['ATR']

                    # Crear orden real de mercado
                    order = exchange.create_market_buy_order(symbol, qty)
                    position = float(order['filled'])

                    msg = f"""📈 [{now_str}] ENTRADA REAL
🔹 {position:.2f} AEUR @ {entry_price:.5f}
🎯 TP: {target_price:.5f} | 🛑 SL: {stop_price:.5f}"""
                    print(msg); send_telegram(msg)

            elif position > 0:
                if last['low'] <= stop_price:
                    exit_price = stop_price * (1 - SLIPPAGE)
                    pnl = (exit_price - entry_price) * position * (1 - FEE)
                    exchange.create_market_sell_order(symbol, position)
                    capital += pnl
                    profit_24h += pnl
                    msg = f"""❌ [{now_str}] STOP LOSS REAL
💸 Salida: {exit_price:.5f}
📉 Pérdida: {pnl:.2f} USDT
💰 Capital actual: {capital:.2f}"""
                    print(msg); send_telegram(msg)
                    position = 0

                elif last['high'] >= target_price:
                    exit_price = target_price * (1 - SLIPPAGE)
                    pnl = (exit_price - entry_price) * position * (1 - FEE)
                    exchange.create_market_sell_order(symbol, position)
                    capital += pnl
                    profit_24h += pnl
                    msg = f"""✅ [{now_str}] TAKE PROFIT REAL
🏁 Salida: {exit_price:.5f}
📈 Ganancia: {pnl:.2f} USDT
💰 Capital actual: {capital:.2f}"""
                    print(msg); send_telegram(msg)
                    position = 0

            if now - last_report_time > timedelta(hours=24):
                rpt = (
                    f"📊 Resumen diario\n"
                    f"Ganancia/Pérdida últimas 24h: {profit_24h:.2f} USDT\n"
                    f"Capital actual: {capital:.2f} USDT"
                )
                send_telegram(rpt)
                profit_24h = 0
                last_report_time = now

            print(f"[{now_str}] Capital actual: {capital:.2f} USDT")
            time.sleep(15)

        except Exception as e:
            print("[Error en ejecución]", e)
            send_telegram(f"⚠️ Error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    run_bot()
