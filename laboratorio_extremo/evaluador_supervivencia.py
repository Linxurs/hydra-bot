import pandas as pd
import glob
import os
from simulador_superhidra import EstrategiaSuperHidra

def probar_escenario(archivo):
    nombre = os.path.basename(archivo).replace('.parquet', '').upper()
    print(f"\n--- Probando Escenario: {nombre} ---")
    
    df = pd.read_parquet(archivo)
    bot = EstrategiaSuperHidra(inversion_inicial=1000.0)
    df = bot.generar_indicadores(df)
    
    max_drawdown = 0.0
    max_balance = 1000.0
    operaciones = 0
    
    for i, row in df.iterrows():
        vela = row.to_dict()
        decision = bot.proximo_paso(vela)
        
        # DEBUG: ¿Por qué no entras?
        if decision == 'ESPERAR' and i % 500 == 0:
            t_alcista = vela["ema_50"] > vela["ema_200"]
            f_trend = vela["adx"] > bot.umbral_adx
            vol_f = vela["volume"] > vela["volumen_ma"]
            macro_f = vela.get("ema_macro", 0) > 0 and vela["close"] > vela["ema_macro"]
            print(f"DEBUG Vela {i}: Alcista:{t_alcista} | Fuerza:{f_trend} | Vol:{vol_f} | Macro:{macro_f} | RSI:{vela['rsi']:.1f}")
            bot.ejecutar_orden('COMPRAR', vela['close'], vela['date'])
            operaciones += 1
        elif 'VENDER' in decision:
            bot.ejecutar_orden('VENDER', vela['close'], vela['date'])
            operaciones += 1
            
        # Calcular Drawdown en tiempo real
        max_balance = max(max_balance, bot.balance_actual)
        dd = (max_balance - bot.balance_actual) / max_balance
        max_drawdown = max(max_drawdown, dd)
        
        if bot.balance_actual <= 0:
            print("☠️ ¡CUENTA LIQUIDADA!")
            break

    print(f"💰 Balance Final: ${bot.balance_actual:.2f}")
    print(f"📉 Max Drawdown: {max_drawdown*100:.2f}%")
    print(f"🔢 Operaciones: {operaciones}")
    status = "✅ SOBREVIVIÓ" if bot.balance_actual > 0 else "❌ MUERTO"
    return {"escenario": nombre, "balance": bot.balance_actual, "dd": max_drawdown, "status": status}

if __name__ == "__main__":
    archivos = glob.glob('datos_caos/*.parquet')
    resultados = []
    for f in archivos:
        resultados.append(probar_escenario(f))
    
    print("\n" + "="*50)
    print("RESUMEN DEL LABORATORIO EXTREMO")
    print("="*50)
    for r in resultados:
        print(f"{r['escenario']:<15} | {r['status']} | Balance: ${r['balance']:>10.2f} | Max DD: {r['dd']*100:>6.2f}%")
