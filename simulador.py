import pandas as pd
import time
# Importamos TODAS las estrategias
from estrategias.cruce_simple import EstrategiaCruce
from estrategias.rsi_rebound import EstrategiaRSI
from estrategias.cerebro import EstrategiaHidra
from estrategias.tvb_breakout import EstrategiaTVB
from estrategias.ehmt_trend import EstrategiaEHMT
from estrategias.super_hidra import EstrategiaSuperHidra

def correr_simulacion():
    print("--- 1. Cargando datos... ---")
    try:
        df_original = pd.read_parquet('datos/btc_usdt_1h.parquet')
        print(f"✅ {len(df_original)} velas cargadas.")
    except FileNotFoundError:
        print("❌ Error: No hay datos. Corre recolector.py primero.")
        return

    # Lista de las clases de estrategias a probar
    clases_estrategias = [
        EstrategiaCruce, 
        EstrategiaRSI, 
        EstrategiaHidra, 
        EstrategiaTVB, 
        EstrategiaEHMT,
        EstrategiaSuperHidra
    ]

    resultados = []

    print("\n--- Iniciando Ejecución Masiva ---")

    for Clase in clases_estrategias:
        bot = Clase() # Instanciamos la estrategia
        print(f"\n🚀 Ejecutando: {bot.nombre}...")
        
        # Copia del DF
        df = df_original.copy()
        
        # Calculando Indicadores
        df = bot.generar_indicadores(df)
        
        # Ejecutando Loop
        operaciones = 0
        for vela in df.itertuples():
            datos_vela = vela._asdict()
            decision = bot.proximo_paso(datos_vela)
            
            if decision == 'COMPRAR':
                bot.ejecutar_orden('COMPRAR', vela.close, vela.date)
                operaciones += 1
            elif decision == 'VENDER':
                bot.ejecutar_orden('VENDER', vela.close, vela.date)
                operaciones += 1
        
        # Guardamos el resultado en una lista
        resultados.append({
            'estrategia': bot.nombre,
            'balance': bot.balance_actual,
            'ops': operaciones
        })

    # Ordenar resultados de mayor a menor balance
    resultados.sort(key=lambda x: x['balance'], reverse=True)

    print("\n" + "="*40)
    print("🏆 TOP FINAL (Ranking) 🏆")
    print("="*40)

    for i, res in enumerate(resultados, 1):
        beneficio = res['balance'] - 1000
        print(f"{i}. {res['estrategia']}")
        print(f"   Balance: ${res['balance']:.2f} | Neto: ${beneficio:.2f} | Ops: {res['ops']}")
        print("-" * 20)

if __name__ == "__main__":
    correr_simulacion()
