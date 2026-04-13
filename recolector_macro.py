import yfinance as yf
import pandas as pd
import os

def descargar_macro_btc():
    print("🚀 Descargando historial macro (1D) de Bitcoin desde Yahoo Finance...")
    
    # Descargar datos desde 2014
    btc = yf.download("BTC-USD", start="2014-09-17", interval="1d")
    
    if btc.empty:
        print("❌ No se pudieron descargar los datos.")
        return

    # Adaptar formato al simulador
    # yfinance devuelve un MultiIndex si no se tiene cuidado, lo aplanamos
    btc = btc.reset_index()
    
    # Renombrar columnas a minúsculas para consistencia
    btc.columns = [col[0].lower() if isinstance(col, tuple) else col.lower() for col in btc.columns]
    
    # Crear columna timestamp (ms) a partir de Date
    btc['timestamp'] = btc['date'].astype('int64') // 10**6
    
    # Seleccionar solo lo necesario
    df_final = btc[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    if not os.path.exists('datos'):
        os.makedirs('datos')
        
    path = 'datos/btc_usd_1d_macro.parquet'
    df_final.to_parquet(path)
    
    print(f"✅ ¡Éxito! {len(df_final)} días de historial guardados.")
    print(f"📅 Desde: {btc['date'].min()} hasta {btc['date'].max()}")
    print(f"📂 Archivo: {path}")

if __name__ == "__main__":
    descargar_macro_btc()
