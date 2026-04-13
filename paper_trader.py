import ccxt
import pandas as pd
import time
import requests
import json
import os
from datetime import datetime
from estrategias.super_hidra import EstrategiaSuperHidra

# CONFIGURACIÓN
SYMBOL = 'BTC/USDT'
TIMEFRAME = '1h'
ARCHIVO_ESTADO = 'estado_cartera.json'

def cargar_estado():
    if not os.path.exists(ARCHIVO_ESTADO):
        # Si no existe, creamos uno nuevo
        return {"balance_usdt": 1000.0, "crypto_tenencia": 0.0, "estado": "LIQUIDO"}
    with open(ARCHIVO_ESTADO, 'r') as f:
        return json.load(f)

def guardar_estado(estado):
    with open(ARCHIVO_ESTADO, 'w') as f:
        json.dump(estado, f, indent=4)

def obtener_datos_recientes(exchange):
    print(f"📡 Conectando a Binance para ver el precio de {SYMBOL}...")
    try:
        # Aumentamos a 1000 velas para que el filtro de 4H tenga datos suficientes
        velas = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=1000) 
        df = pd.DataFrame(velas, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        cols = ['open', 'high', 'low', 'close', 'volume']
        df[cols] = df[cols].astype('float32')
        return df
    except Exception as e:
        print(f"⚠️ Error de conexión: {e}")
        return None

# --- CONFIGURACIÓN TELEGRAM ---
TELEGRAM_TOKEN = "8475810993:AAEN7gg56CK0LmMQcmu_IfrYlLUfbmd5aqg"
TELEGRAM_CHAT_ID = "1842573935"

def enviar_telegram(mensaje):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        datos = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}
        requests.post(url, data=datos, timeout=5)
    except Exception as e:
        print(f"Error enviando mensaje: {e}")

def ejecutar_bot_vivo():
    exchange = ccxt.binance()
    bot_cerebro = EstrategiaSuperHidra()
    
    print("🤖 INICIANDO HIDRA PAPER-TRADER (Modo: Simulación Real)")
    print("Presiona Ctrl+C para detenerlo.\n")

    # --- PRUEBA DE CONEXIÓN ---
    try:
        enviar_telegram("🚀 ¡HOLA! El Bot Hidra se ha iniciado correctamente y está vigilando el mercado.")
        print("✅ Mensaje de prueba enviado a Telegram.")
    except Exception as e:
        print(f"❌ Error enviando mensaje de prueba: {e}")

    while True:
        # 1. Cargar Estado de la Cartera
        cartera = cargar_estado()
        
        # Sincronizar el cerebro del bot con la cartera real
        if cartera['estado'] == 'COMPRADO':
            bot_cerebro.posicion = 'COMPRADO'
        else:
            bot_cerebro.posicion = None

        # 2. Obtener datos del mercado AHORA
        df = obtener_datos_recientes(exchange)
        
        if df is not None:
            # Precio actual (última vela cerrada o la actual en movimiento)
            precio_actual = df.iloc[-1]['close']
            fecha_actual = df.iloc[-1]['date']

            # 3. Calcular Indicadores
            df = bot_cerebro.generar_indicadores(df)
            
            # 4. Preguntar al Cerebro
            # Tomamos la PENÚLTIMA vela (iloc[-2]) porque la última se está moviendo todavía
            # y no queremos falsas señales. La penúltima ya "cerró".
            vela_analizada = df.iloc[-2].to_dict()
            decision = bot_cerebro.proximo_paso(vela_analizada)
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Precio: ${precio_actual:.2f} | Decisión: {decision} | Estado: {cartera['estado']}")
            
            # 5. Ejecutar Acciones (Simuladas)
            if decision == 'COMPRAR' and cartera['estado'] == 'LIQUIDO':
                # Compramos todo
                cantidad_btc = cartera['balance_usdt'] / precio_actual
                cartera['crypto_tenencia'] = cantidad_btc
                cartera['balance_usdt'] = 0
                cartera['estado'] = 'COMPRADO'
                cartera['precio_compra'] = float(precio_actual)
                
                print(f"🟢 ¡ORDEN DE COMPRA EJECUTADA! {cantidad_btc:.6f} BTC a ${precio_actual}")
                guardar_estado(cartera)

                mensaje = f"🟢 COMPRA HIDRA\nPrecio: ${precio_actual}\nCantidad: {cantidad_btc:.6f} BTC"
                print(mensaje)
                enviar_telegram(mensaje) # <--- NUEVA LÍNEA
                
            elif decision == 'VENDER' and cartera['estado'] == 'COMPRADO':
                # Vendemos todo
                nuevo_balance = cartera['crypto_tenencia'] * precio_actual
                ganancia = nuevo_balance - (cartera['crypto_tenencia'] * cartera['precio_compra'])
                
                cartera['balance_usdt'] = nuevo_balance
                cartera['crypto_tenencia'] = 0
                cartera['estado'] = 'LIQUIDO'
                
                emoji = "💰" if ganancia > 0 else "🔻"
                print(f"🔴 ¡ORDEN DE VENTA EJECUTADA! Balance Nuevo: ${nuevo_balance:.2f} ({emoji} {ganancia:.2f})")
                guardar_estado(cartera)

                mensaje = f"🔴 VENTA HIDRA\nPrecio: ${precio_actual}\nGanancia: {emoji} ${ganancia:.2f}\nBalance: ${nuevo_balance:.2f}"
                print(mensaje)
                enviar_telegram(mensaje) # <--- NUEVA LÍNEA

        # 6. Dormir hasta la siguiente hora
        # Para pruebas, vamos a revisar cada 60 segundos. 
        # En producción real sería: time.sleep(3600)
        print("💤 Durmiendo 60 segundos...")
        time.sleep(60)

if __name__ == "__main__":
    ejecutar_bot_vivo()
