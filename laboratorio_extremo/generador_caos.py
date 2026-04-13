import pandas as pd
import numpy as np
import datetime

def crear_df_base(n_velas, precio_inicial=50000.0):
    start_date = datetime.datetime(2026, 1, 1)
    dates = [start_date + datetime.timedelta(hours=i) for i in range(n_velas)]
    df = pd.DataFrame({
        'timestamp': [int(d.timestamp() * 1000) for d in dates],
        'date': dates,
        'open': precio_inicial, 'high': precio_inicial, 'low': precio_inicial, 'close': precio_inicial,
        'volume': 100.0
    })
    return df

def escenario_lateral_infinito(n_velas=5000):
    """Genera un mercado lateral ruidoso (el peor enemigo de las tendencias)"""
    df = crear_df_base(n_velas)
    precio = 50000.0
    for i in range(n_velas):
        # Ruido aleatorio del 2% para forzar señales falsas
        cambio = np.random.uniform(-0.02, 0.021) 
        precio = precio * (1 + cambio)
        df.loc[i, 'close'] = precio
        df.loc[i, 'high'] = precio * 1.01
        df.loc[i, 'low'] = precio * 0.99
        df.loc[i, 'open'] = precio / (1 + cambio)
    return df

def escenario_cisne_negro(n_velas=5000, crash_pct=0.60):
    """Mercado que sube sanamente y luego cae un 60% en 5 horas"""
    df = crear_df_base(n_velas)
    precio = 30000.0
    punto_crash = 4000 # Cerca del final
    for i in range(n_velas):
        if i < punto_crash:
            cambio = np.random.uniform(0.0001, 0.002) # Subida lenta y segura
        elif i < punto_crash + 5:
            cambio = - (crash_pct / 5) # Caída relámpago
        else:
            cambio = np.random.uniform(-0.01, 0.01) # Caos post-crash
        
        precio = precio * (1 + cambio)
        df.loc[i, 'close'] = precio
        df.loc[i, 'high'] = precio * 1.005
        df.loc[i, 'low'] = precio * 0.995
        df.loc[i, 'open'] = precio / (1 + cambio)
    return df

def escenario_burbuja_parabolica(n_velas=1000):
    """Subida exponencial y colapso total (Pump and Dump)"""
    df = crear_df_base(n_velas)
    precio = 10000.0
    for i in range(n_velas):
        if i < 700:
            cambio = 0.003 + (i/20000) # Aceleración
        else:
            cambio = -0.05 # Desplome del 5% por hora
        
        precio = max(precio * (1 + cambio), 100) # No bajar de 100
        df.loc[i, 'close'] = precio
        df.loc[i, 'high'] = precio * 1.02
        df.loc[i, 'low'] = precio * 0.98
        df.loc[i, 'open'] = precio / (1 + cambio)
    return df

if __name__ == "__main__":
    import os
    if not os.path.exists('datos_caos'): os.makedirs('datos_caos')
    
    escenario_lateral_infinito().to_parquet('datos_caos/lateral.parquet')
    escenario_cisne_negro().to_parquet('datos_caos/cisne_negro.parquet')
    escenario_burbuja_parabolica().to_parquet('datos_caos/burbuja.parquet')
    print("✅ Escenarios de CAOS generados en /datos_caos")
