import os
import time
from datetime import datetime, timedelta
import ccxt
import pandas as pd
import requests

# ==========================================
# 1. CONFIGURACIÓN
# ==========================================
DESCARGAR_PRE_2017 = False  
# --------------------------

exchange = ccxt.binance({"enableRateLimit": True})
symbol_ccxt = "SOL/USDT"
timeframe = "1m"
limit = 1000

def obtener_datos_ccxt(since_ms=None):
    print(f"--- Iniciando descarga de {symbol_ccxt} ({timeframe}) desde CCXT ---")
    if since_ms is None:
        since_ms = exchange.parse8601("2017-01-01T00:00:00Z")
    
    print(f"Descargando desde: {datetime.fromtimestamp(since_ms/1000)}")
    
    all_candles = []
    while True:
        try:
            candles = exchange.fetch_ohlcv(symbol_ccxt, timeframe, since_ms, limit)
            if not candles:
                break
            
            all_candles.extend(candles)
            since_ms = candles[-1][0] + 1
            
            print(f"Velas acumuladas: {len(all_candles)} | Siguiente: {datetime.fromtimestamp(since_ms/1000)}")
            
            if candles[-1][0] >= exchange.milliseconds() - 60000:
                break
                
            time.sleep(exchange.rateLimit / 1000)
        except Exception as e:
            print(f"Error en CCXT: {e}")
            break
            
    print(f"--- Descarga completada CCXT. Total velas: {len(all_candles)} ---")
    return pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])

def guardar_datos(df):
    if df.empty:
        print("No hay datos para guardar.")
        return

    cols_float = ["open", "high", "low", "close", "volume"]
    df[cols_float] = df[cols_float].astype("float32")
    df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
    os.makedirs("datos", exist_ok=True)
    archivo = "datos/sol_usdt_1m.parquet"
    df.to_parquet(archivo)
    print(f"✅ Datos guardados en: {archivo} | Total filas: {len(df)}")

if __name__ == "__main__":
    start_ms = int((datetime.now() - timedelta(days=15)).timestamp() * 1000)
    df = obtener_datos_ccxt(start_ms)
    guardar_datos(df)
