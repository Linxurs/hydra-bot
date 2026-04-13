import pandas as pd
import numpy as np
import datetime
import os

def crear_la_sierra():
    # Necesitamos muchas velas para que las medias móviles y el ADX se calibren (EMA 200 necesita al menos 1000 velas)
    n_velas = 8000 
    precio = 50000.0
    df_list = []
    
    # 1. CALIBRACIÓN (3000 velas de mercado normal alcista)
    # Esto asegura que EMA 50 > EMA 200 y que la tendencia macro sea alcista
    for i in range(3000):
        cambio = np.random.normal(0.0002, 0.002) # Subida leve con ruido
        precio *= (1 + cambio)
        vol = np.random.uniform(50, 150)
        df_list.append({'close': precio, 'high': precio*(1+abs(cambio)), 'low': precio*(1-abs(cambio)), 'volume': vol})

    # 2. LA TRAMPA (Repetimos 5 veces el ciclo de pérdida masiva)
    for ciclo in range(5):
        # A. EL CEBO (Pump de 200 horas): Sube un 10% para que el ADX explote y el bot entre
        for i in range(200):
            cambio = 0.001 + np.random.normal(0, 0.001)
            precio *= (1 + cambio)
            vol = np.random.uniform(200, 500) # Volumen alto para activar entrada
            df_list.append({'close': precio, 'high': precio*1.005, 'low': precio*0.995, 'volume': vol})
        
        # B. EL MAZAZO (Flash Crash): Cae un 12% en 2 horas
        # Esto es mayor al Stop Loss (7%) pero con apalancamiento 1.5x es una pérdida del 18% del balance total
        for i in range(2):
            precio *= 0.94 
            df_list.append({'close': precio, 'high': precio*1.01, 'low': precio*0.98, 'volume': 1000})
            
        # C. EL REBOTE DEL GATO MUERTO (Lateralidad dolorosa)
        # El bot intentará recuperar, pero el mercado solo oscilará para cobrar comisiones
        for i in range(500):
            cambio = np.random.normal(0, 0.005)
            precio *= (1 + cambio)
            df_list.append({'close': precio, 'high': precio*1.005, 'low': precio*0.995, 'volume': 100})

    df = pd.DataFrame(df_list)
    start_date = datetime.datetime(2026, 1, 1)
    df['date'] = [start_date + datetime.timedelta(hours=i) for i in range(len(df))]
    df['timestamp'] = [int(d.timestamp() * 1000) for d in df['date']]
    
    if not os.path.exists('datos_caos'): os.makedirs('datos_caos')
    df.to_parquet('datos_caos/sierra_diablo.parquet')
    print("🔥 Escenario 'LA SIERRA DEL DIABLO' generado. Si el bot sobrevive a esto, es inmortal.")

if __name__ == "__main__":
    crear_la_sierra()
