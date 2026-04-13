import ccxt
import pandas as pd
import time
from datetime import datetime

# 1. CONFIGURACIÓN
# Usamos Binance, pero podrías cambiarlo por 'kraken' o 'bybit' fácilmente.
exchange = ccxt.binance({
    'enableRateLimit': True  # Importante: Evita que Binance nos bloquee por pedir datos muy rápido
})

symbol = 'BTC/USDT'  # La moneda que queremos
timeframe = '1h'     # Velas de 1 hora
limit = 1000         # Cuantas velas pedimos por llamada (Binance suele dejar 1000 máx)

def obtener_datos():
    print(f"--- Iniciando descarga de {symbol} ({timeframe}) ---")
    
    # Lista para guardar los pedacitos de datos
    all_candles = []
    
    # Fecha de inicio: 1 de Enero de 2023 (en milisegundos, como lo pide Binance)
    since = exchange.parse8601('2017-01-01T00:00:00Z')
    
    # Bucle infinito hasta que lleguemos a hoy
    while True:
        try:
            print(f"Descargando desde: {exchange.iso8601(since)}")
            
            # Pedimos las velas al exchange
            candles = exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            
            # Si no nos devuelve nada, es que ya terminamos
            if not candles:
                break
            
            # Guardamos lo que bajamos
            all_candles += candles
            
            # Actualizamos la fecha 'since' para la siguiente vuelta
            # Tomamos el tiempo de la última vela + 1 segundo
            since = candles[-1][0] + 1
            
            # Pequeña pausa para no saturar tu CPU ni al exchange
            time.sleep(exchange.rateLimit / 1000)
            
            # SEGURIDAD: Si ya llegamos al presente, paramos
            now = exchange.milliseconds()
            if since >= now:
                break
                
        except Exception as e:
            print(f"Error: {e}")
            break

    print(f"--- Descarga completada. Total velas: {len(all_candles)} ---")
    return all_candles

def guardar_datos(candles):
    # Convertimos la lista de datos a un formato que Pandas entienda (DataFrame)
    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # Convertimos el tiempo feo (1672531200000) a algo legible (2023-01-01 00:00:00)
    df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    # 2. OPTIMIZACIÓN DE MEMORIA (Vital para tus 4GB RAM)
    # Convertimos los números gigantes (float64) a números normales (float32)
    # Esto reduce el uso de memoria a la MITAD sin perder precisión útil.
    cols = ['open', 'high', 'low', 'close', 'volume']
    df[cols] = df[cols].astype('float32')
    
    # Guardamos en formato PARQUET (Comprimido y rápido para tu HDD)
    archivo = 'datos/btc_usdt_1h.parquet'
    df.to_parquet(archivo, engine='fastparquet')
    print(f"Datos guardados exitosamente en: {archivo}")

# EJECUCIÓN
if __name__ == "__main__":
    datos = obtener_datos()
    if datos:
        guardar_datos(datos)
