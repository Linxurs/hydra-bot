import pandas as pd
import numpy as np
import datetime
import os

def crear_escenario_liquidacion():
    # 5000 velas para calentar indicadores
    n_total = 5000 
    precio = 40000.0
    df_list = []
    
    # 1. SUBIDA "SEGURA" (4000 velas)
    # EMA 50 > 200, ADX subiendo, Close > EMA Macro
    for i in range(4000):
        cambio = 0.0005 + np.random.normal(0, 0.001)
        precio *= (1 + cambio)
        vol = 100 * (1 + np.random.exponential(1))
        df_list.append({'close': precio, 'high': precio*1.005, 'low': precio*0.995, 'volume': vol})

    # 2. EL PICO DE EUFORIA (200 velas)
    # Aquí el ADX debe superar 35 para forzar apalancamiento 1.5x
    for i in range(200):
        cambio = 0.005 # Subida fuerte del 0.5% por hora
        precio *= (1 + cambio)
        vol = 1000 # Volumen muy alto para asegurar entrada
        df_list.append({'close': precio, 'high': precio*1.01, 'low': precio*0.99, 'volume': vol})

    # 3. EL DESASTRE (10 velas)
    # El precio cae un 10% POR HORA durante 5 horas
    # Con 1.5x de apalancamiento, una caída del 10% es una pérdida del 15% del balance.
    # Si el stop loss no cierra a tiempo o hay deslizamiento, el DD será brutal.
    for i in range(10):
        precio *= 0.85 # -15% por hora. Esto es una MASACRE.
        df_list.append({'close': precio, 'high': precio*1.01, 'low': precio*0.80, 'volume': 5000})

    df = pd.DataFrame(df_list)
    start_date = datetime.datetime(2023, 1, 1)
    df['date'] = [start_date + datetime.timedelta(hours=i) for i in range(len(df))]
    df['timestamp'] = [int(d.timestamp() * 1000) for d in df['date']]
    
    if not os.path.exists('datos_caos'): os.makedirs('datos_caos')
    df.to_parquet('datos_caos/liquidacion_total.parquet')
    print("💀 Escenario 'LIQUIDACIÓN TOTAL' generado. Si no muere aquí, es porque el bot es un fantasma.")

if __name__ == "__main__":
    crear_escenario_liquidacion()
