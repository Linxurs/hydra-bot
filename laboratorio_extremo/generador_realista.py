import pandas as pd
import numpy as np
import datetime
import os

def crear_escenario_realista_y_mortal():
    # 15,000 velas para asegurar que hasta la EMA 200 de 4h esté perfecta
    n_total = 15000 
    precio = 30000.0
    df_list = []
    
    # FASE 1: CALIBRACIÓN LARGA (10,000 velas de mercado alcista real con mucho ruido)
    # Esto "engaña" al bot haciéndole creer que el mercado es seguro.
    for i in range(10000):
        cambio = np.random.normal(0.00015, 0.003) # Subida lenta pero con "serrucho"
        precio *= (1 + cambio)
        # Volumen con picos (indispensable para que volume > vol_ma)
        vol = 100 * (1 + np.random.exponential(1.5)) 
        df_list.append({'close': precio, 'high': precio*1.01, 'low': precio*0.99, 'volume': vol})

    # FASE 2: EL CEBO DEFINITIVO (1,000 velas de "Bull Run" claro)
    # Esto disparará el ADX por encima de 35 (Apalancamiento 1.5x)
    for i in range(1000):
        cambio = 0.002 + np.random.normal(0, 0.002)
        precio *= (1 + cambio)
        vol = 500 * (1 + np.random.exponential(2)) 
        df_list.append({'close': precio, 'high': precio*1.005, 'low': precio*0.995, 'volume': vol})

    # FASE 3: EL "FLASH CRASH" Y REBOTE FALSO (Aquí es donde ocurre el 56% de DD)
    # Caída del 15% -> Rebote del 5% (el bot vuelve a entrar) -> Caída del 20%
    ciclo_mortal = [
        (-0.15, 5),   # Gran caída en 5 horas
        (0.05, 20),   # Rebote falso largo
        (-0.25, 10)   # El hachazo final
    ]
    
    for caída, duración in ciclo_mortal:
        step = caída / duración
        for i in range(duración):
            precio *= (1 + step)
            vol = 1000 * (1 + np.random.exponential(3))
            df_list.append({'close': precio, 'high': precio*1.02, 'low': precio*0.98, 'volume': vol})

    df = pd.DataFrame(df_list)
    start_date = datetime.datetime(2023, 1, 1) # Fecha antigua para que el resample de 4h funcione bien
    df['date'] = [start_date + datetime.timedelta(hours=i) for i in range(len(df))]
    df['timestamp'] = [int(d.timestamp() * 1000) for d in df['date']]
    
    if not os.path.exists('datos_caos'): os.makedirs('datos_caos')
    df.to_parquet('datos_caos/trampa_maestra.parquet')
    print("🎯 Escenario 'TRAMPA MAESTRA' generado. Si esto no lo hace operar, nada lo hará.")

if __name__ == "__main__":
    crear_escenario_realista_y_mortal()
