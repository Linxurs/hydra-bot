import pandas as pd
import requests
import json
import os
from google import genai
from datetime import datetime

# ==========================================
# GUARDIÁN HYDRA 7.0: AUTO-RECOLECTOR Y ANALISTA
# ==========================================

def descargar_velas_recientes(symbol="BTCUSDT", interval="1h"):
    """Descarga las últimas 1000 velas de Binance para tener datos frescos."""
    print(f"📡 Sincronizando con Binance ({symbol})...")
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": 1000}
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        df_new = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'
        ])
        df_new[['open', 'high', 'low', 'close', 'volume']] = df_new[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
        
        # Guardar/Actualizar el parquet local
        path = 'datos/btc_usdt_1h.parquet'
        if os.path.exists(path):
            df_old = pd.read_parquet(path)
            # Unimos y eliminamos duplicados por timestamp
            df_final = pd.concat([df_old, df_new]).drop_duplicates(subset=['timestamp']).sort_values('timestamp')
        else:
            df_final = df_new
            
        df_final.to_parquet(path)
        print(f"✅ Datos actualizados. Total velas en base: {len(df_final)}")
        return df_final
    except Exception as e:
        print(f"❌ Error al descargar de Binance: {e}")
        return None

def pedir_consejo_a_gemini(contexto_operacion=None):
    """Consulta a Gemini sobre el estado actual o sobre una operacion especifica."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return {"modo": "NORMAL", "leverage": 1, "analisis": "Sin API Key"}

    client = genai.Client(api_key=api_key)
    df = pd.read_parquet('datos/btc_usdt_1h.parquet').tail(168) # Ultima semana
    
    resumen = {
        "precio_actual": float(df['close'].iloc[-1]),
        "volumen_avg": float(df['volume'].mean()),
        "cambio_7d": float(((df['close'].iloc[-1] / df['close'].iloc[0]) - 1) * 100)
    }

    prompt = f"""
    Eres el estratega jefe del bot 'Super Hidra'. 
    DATOS ACTUALES: {json.dumps(resumen)}
    """
    
    if contexto_operacion:
        prompt += f"\nANALIZA ESTA OPERACION: {json.dumps(contexto_operacion)}"
        prompt += "\n¿Fue una buena entrada/salida? ¿Debimos apalancarnos x3 o protegernos?"
    else:
        prompt += "\nDecide el modo de riesgo (PROTECCION, NORMAL, AGRESIVO) y el apalancamiento (1 o 3)."

    prompt += "\nResponde estrictamente en JSON: {\"modo\": \"...\", \"leverage\": 1|3, \"analisis\": \"...\"}"

    try:
        response = client.models.generate_content(model='gemini-2.5-flash-lite', contents=prompt)
        return json.loads(response.text.replace('```json', '').replace('```', '').strip())
    except:
        return {"modo": "NORMAL", "leverage": 1, "analisis": "Error en consulta"}

def ejecutar_guardian_completo():
    # 1. Bajamos datos frescos
    descargar_velas_recientes()
    
    # 2. Analizamos sentimiento macro
    decision = pedir_consejo_a_gemini()
    
    # 3. Guardamos el estado para el simulador
    with open('estado_guardian.json', 'w') as f:
        json.dump(decision, f)
        
    print(f"\n🛡️ GUARDIÁN REPORTA: {decision['modo']} (x{decision['leverage']})")
    print(f"💬 RAZÓN: {decision['analisis']}")

if __name__ == "__main__":
    ejecutar_guardian_completo()
