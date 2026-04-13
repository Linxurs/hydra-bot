import pandas as pd
import numpy as np
import datetime
import os

def crear_asesino_v2():
    n_velas = 10000 # Más tiempo para que las medias (EMA 200) se estabilicen
    precio_actual = 50000.0
    df_list = []
    
    # FASE 1: CREAR HISTORIAL (2000 velas de calma para que las EMAs existan)
    for i in range(2000):
        precio_actual *= (1 + np.random.uniform(-0.0005, 0.0005))
        df_list.append({'close': precio_actual, 'high': precio_actual*1.001, 'low': precio_actual*0.999, 'volume': 100.0})

    # FASE 2: EL CEBO (Subida constante para forzar el cruce y el ADX)
    # Necesitamos que la EMA 50 suba por encima de la EMA 200 y el ADX suba.
    for i in range(2000):
        precio_actual *= 1.0005 # +0.05% por hora = +1.2% diario
        df_list.append({'close': precio_actual, 'high': precio_actual*1.001, 'low': precio_actual*0.999, 'volume': 100.0})

    # FASE 3: LA TRAMPA (10 Ciclos de entrada y hachazo)
    for ciclo in range(10):
        # A. Preparar la entrada: Subida con volumen
        for i in range(100):
            precio_actual *= 1.001
            vol = 500.0 if i > 90 else 100.0 # Pico de volumen al final
            df_list.append({'close': precio_actual, 'high': precio_actual*1.002, 'low': precio_actual*0.998, 'volume': vol})
        
        # B. EL HACHAZO: Caída del 10% en 1 hora (salta el Stop Loss de 7%)
        precio_actual *= 0.90
        df_list.append({'close': precio_actual, 'high': precio_actual*1.01, 'low': precio_actual*0.99, 'volume': 2000.0})
        
        # C. Recuperación falsa para que el bot vuelva a confiar
        for i in range(300):
            precio_actual *= 1.0002
            df_list.append({'close': precio_actual, 'high': precio_actual*1.001, 'low': precio_actual*0.999, 'volume': 100.0})

    df = pd.DataFrame(df_list)
    start_date = datetime.datetime(2026, 1, 1)
    dates = [start_date + datetime.timedelta(hours=i) for i in range(len(df))]
    df['date'] = dates
    df['timestamp'] = [int(d.timestamp() * 1000) for d in dates]
    
    if not os.path.exists('datos_caos'): os.makedirs('datos_caos')
    df.to_parquet('datos_caos/trampa_mortal.parquet')
    print("😈 Escenario 'TRAMPA MORTAL' generado con condiciones técnicas exactas.")

if __name__ == "__main__":
    crear_asesino_v2()
