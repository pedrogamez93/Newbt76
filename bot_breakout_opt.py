# bot_trading_sol_combo.py (swing + scalping inteligente refinado)

import ccxt
import pandas as pd
import numpy as np
import time, os, requests
from datetime import datetime
from dotenv import load_dotenv

# === CONFIGURACIÓN ===
load_dotenv()
API_KEY = os.getenv("BINANCE_KEY")
API_SECRET = os.getenv("BINANCE_SECRET")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "SOL/FDUSD"
TIMEFRAME = "1m"
CAPITAL = 280
MAX_POSITIONS = 4
RISK_PCT = 0.05  # ajustado para menor riesgo
TRAIL_TRIGGER = 0.0025
TRAIL_GAP = 0.0010

positions_swing = []
positions_scalp = []
trailing_active = False
highest_price = 0


def send_telegram(msg):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TG_CHAT_ID, "text": msg})
    except:
        pass


def fetch_data(limit=120):
    ohlcv = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    df.set_index('ts', inplace=True)
    return df


def compute_indicators(df):
    df['mb'] = df['close'].rolling(14).mean()
    df['std'] = df['close'].rolling(14).std()
    df['bb_low'] = df['mb'] - 2.5 * df['std']
    df['bb_up'] = df['mb'] + 2.5 * df['std']
    df['ema_fast'] = df['close'].ewm(span=5).mean()
    df['ema_slow'] = df['close'].ewm(span=21).mean()
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.ewm(14).mean() / (loss.ewm(14).mean() + 1e-10)
    df['rsi'] = 100 - 100 / (1 + rs)
    df['range10'] = df['high'].rolling(10).max() - df['low'].rolling(10).min()
    df['body'] = abs(df['close'] - df['open'])
    df['wick_lower'] = df[['open', 'close']].min(axis=1) - df['low']
    return df


def run_bot():
    global CAPITAL, positions_swing, positions_scalp, trailing_active, highest_price
    send_telegram("🤖 Bot combinado SOL swing + scalping refinado iniciado")

    while True:
        try:
            df = fetch_data()
            df = compute_indicators(df)
            last = df.iloc[-1]
            price = last['close']
            hour = last.name.hour
            vol_avg = df['volume'].iloc[-20:].mean()
            vol_curr = last['volume']

            if not (4 <= hour <= 9):
                time.sleep(60)
                continue

            # === SWING ===
            if last['range10'] > 0.002 * price:
                if (last['rsi'] < 33 and last['wick_lower'] > 2 * last['body'] and vol_curr > 1.4 * vol_avg and len(positions_swing) < MAX_POSITIONS):
                    amount = CAPITAL * RISK_PCT
                    qty = amount / price
                    positions_swing.append((price, qty))
                    CAPITAL -= qty * price
                    send_telegram(f"🟢 COMPRA SWING {qty:.2f} @ {price:.3f}")

                if (last['ema_fast'] > last['ema_slow'] and df['ema_fast'].iloc[-3] < df['ema_slow'].iloc[-3] and last['close'] > last['bb_up'] and last['rsi'] > 61):
                    amount = CAPITAL * RISK_PCT
                    qty = amount / price
                    positions_swing.append((price, qty))
                    CAPITAL -= qty * price
                    send_telegram(f"🚀 BREAKOUT SWING {qty:.2f} @ {price:.3f}")

                # TP trailing swing
                if positions_swing:
                    total_qty = sum(q for _, q in positions_swing)
                    avg_price = sum(p * q for p, q in positions_swing) / total_qty
                    gain_pct = (price - avg_price) / avg_price

                    if gain_pct >= TRAIL_TRIGGER:
                        if not trailing_active:
                            highest_price = price
                            trailing_active = True
                            send_telegram("📈 TP swing activado")
                        elif price > highest_price:
                            highest_price = price
                        elif price < highest_price - TRAIL_GAP:
                            pnl = (price - avg_price) * total_qty
                            CAPITAL += total_qty * price
                            positions_swing.clear()
                            trailing_active = False
                            send_telegram(f"✅ TP SWING {total_qty:.2f} @ {price:.3f} → +{pnl:.2f} USDT")

                if positions_swing and last['rsi'] > 63:
                    total_qty = sum(q for _, q in positions_swing)
                    avg_price = sum(p * q for p, q in positions_swing) / total_qty
                    pnl = (price - avg_price) * total_qty
                    CAPITAL += total_qty * price
                    positions_swing.clear()
                    trailing_active = False
                    send_telegram(f"🔴 SL SWING RSI {total_qty:.2f} @ {price:.3f} → PnL: {pnl:.2f} USDT")

            # === SCALPING ===
            if last['body'] > 0.003 * price and vol_curr > 1.2 * vol_avg and last['ema_fast'] > last['ema_slow'] and len(positions_scalp) < MAX_POSITIONS:
                amount = CAPITAL * RISK_PCT
                qty = amount / price
                positions_scalp.append((price, qty, price))  # guardamos también highest_price
                CAPITAL -= qty * price
                send_telegram(f"⚡ SCALPING ENTRY {qty:.2f} @ {price:.3f}")

            # TP trailing scalping
            for i, (entry_price, qty, high) in enumerate(positions_scalp[:]):
                new_high = max(high, price)
                gain_pct = (new_high - entry_price) / entry_price
                if gain_pct >= TRAIL_TRIGGER:
                    if price < new_high - TRAIL_GAP:
                        pnl = (price - entry_price) * qty
                        CAPITAL += qty * price
                        positions_scalp.pop(i)
                        send_telegram(f"✅ TP SCALP {qty:.2f} @ {price:.3f} → +{pnl:.2f} USDT")
                    else:
                        positions_scalp[i] = (entry_price, qty, new_high)

            time.sleep(30)

        except Exception as e:
            send_telegram(f"⚠️ Error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })
    run_bot()
