"""
╔══════════════════════════════════════════════════════════╗
║         HIDRA BOT REAL - Binance Live Trading            ║
║         Estrategia: Super Hidra (ADX + Filtro 4H)        ║
╚══════════════════════════════════════════════════════════╝

INSTALACIÓN:
    pip install ccxt pandas numpy requests python-dotenv

CONFIGURACIÓN:
    1. Creá un archivo .env en la misma carpeta con:
        BINANCE_API_KEY=tu_api_key
        BINANCE_SECRET=tu_secret
        TELEGRAM_TOKEN=tu_token_bot
        TELEGRAM_CHAT_ID=tu_chat_id
    
    2. En Binance, creá una API Key con permisos de:
        ✅ Spot Trading habilitado
        ❌ Retiros DESACTIVADO (por seguridad)
        ✅ Restringí la IP a la de tu servidor/PC

    3. Ajustá la CONFIGURACIÓN más abajo antes de correr.

USO:
    python hidra_bot_real.py
"""

import ccxt
import pandas as pd
import numpy as np
import time
import json
import os
import requests
import traceback
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ══════════════════════════════════════════════════════
#  CONFIGURACIÓN — Revisá esto antes de correr
# ══════════════════════════════════════════════════════

CONFIG = {
    # Par a operar
    "symbol": "BTC/USDT",
    "base_asset": "BTC",
    "quote_asset": "USDT",

    # Capital máximo a usar en USDT (nunca gastará más que esto)
    "capital_maximo_usdt": 400.0,

    # Porcentaje del capital disponible a usar por operación (1.0 = 100%)
    "pct_capital_por_trade": 1.0,

    # MODO SEGURO: True = solo simula, no hace órdenes reales
    # Poné False cuando estés listo para operar real
    "modo_paper": True,

    # Intervalo entre ciclos en segundos (3600 = 1 hora)
    # Usá 60 para pruebas, 3600 para producción
    "intervalo_segundos": 3600,

    # Cuántas velas históricas descargar (mínimo 300 para que los indicadores se estabilicen)
    "velas_historia": 600,

    # Archivo donde se guarda el estado entre reinicios
    "archivo_estado": "estado_hidra_real.json",
}

# ══════════════════════════════════════════════════════
#  CREDENCIALES (desde .env o hardcodeadas acá como último recurso)
# ══════════════════════════════════════════════════════

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET  = os.getenv("BINANCE_SECRET",  "")
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN",  "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ══════════════════════════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════════════════════════

def enviar_telegram(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception:
        pass


def log(msg: str, telegram: bool = False):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linea = f"[{timestamp}] {msg}"
    print(linea)
    if telegram:
        enviar_telegram(linea)


# ══════════════════════════════════════════════════════
#  ESTADO PERSISTENTE
# ══════════════════════════════════════════════════════

ESTADO_INICIAL = {
    "posicion": "LIQUIDO",          # LIQUIDO o COMPRADO
    "precio_compra": 0.0,
    "cantidad_btc": 0.0,
    "usdt_en_trade": 0.0,
    "max_precio_visto": 0.0,
    "operaciones": [],
    "balance_inicial_usdt": CONFIG["capital_maximo_usdt"],
}


def cargar_estado() -> dict:
    path = CONFIG["archivo_estado"]
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return ESTADO_INICIAL.copy()


def guardar_estado(estado: dict):
    with open(CONFIG["archivo_estado"], "w") as f:
        json.dump(estado, f, indent=2, default=str)


# ══════════════════════════════════════════════════════
#  CONEXIÓN A BINANCE
# ══════════════════════════════════════════════════════

def crear_exchange() -> ccxt.binance:
    return ccxt.binance({
        "apiKey":         BINANCE_API_KEY,
        "secret":         BINANCE_SECRET,
        "enableRateLimit": True,
        "options":        {"defaultType": "spot"},
    })


def obtener_balance_usdt(exchange) -> float:
    balance = exchange.fetch_balance()
    return float(balance["USDT"]["free"])


def obtener_balance_btc(exchange) -> float:
    balance = exchange.fetch_balance()
    return float(balance["BTC"]["free"])


def obtener_precio_actual(exchange) -> float:
    ticker = exchange.fetch_ticker(CONFIG["symbol"])
    return float(ticker["last"])


def obtener_velas(exchange) -> pd.DataFrame:
    velas = exchange.fetch_ohlcv(
        CONFIG["symbol"], "1h", limit=CONFIG["velas_historia"]
    )
    df = pd.DataFrame(
        velas, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
    df[["open", "high", "low", "close", "volume"]] = df[
        ["open", "high", "low", "close", "volume"]
    ].astype(float)
    return df


# ══════════════════════════════════════════════════════
#  ESTRATEGIA SUPER HIDRA
# ══════════════════════════════════════════════════════

def generar_indicadores(df: pd.DataFrame) -> pd.DataFrame:
    # EMA 50 y 200
    df["ema_50"]  = df["close"].ewm(span=50,  adjust=False).mean()
    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()

    # RSI 14
    delta = df["close"].diff()
    gain  = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs    = gain / (loss + 1e-10)
    df["rsi"] = 100 - (100 / (1 + rs))

    # ATR 14
    df["tr"] = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            abs(df["high"] - df["close"].shift(1)),
            abs(df["low"]  - df["close"].shift(1))
        )
    )
    df["atr"] = df["tr"].rolling(window=14).mean()

    # ADX 14
    up   = df["high"] - df["high"].shift(1)
    down = df["low"].shift(1) - df["low"]
    pdm  = np.where((up > down) & (up > 0), up, 0)
    mdm  = np.where((down > up) & (down > 0), down, 0)

    tr_s   = df["tr"].ewm(alpha=1/14, min_periods=14).mean()
    pdm_s  = pd.Series(pdm, index=df.index).ewm(alpha=1/14, min_periods=14).mean()
    mdm_s  = pd.Series(mdm, index=df.index).ewm(alpha=1/14, min_periods=14).mean()

    pdi = 100 * (pdm_s / (tr_s + 1e-10))
    mdi = 100 * (mdm_s / (tr_s + 1e-10))
    dx  = 100 * abs(pdi - mdi) / (pdi + mdi + 1e-10)
    df["adx"] = dx.ewm(alpha=1/14, min_periods=14).mean()

    # Bollinger Width
    df["sma_20"]  = df["close"].rolling(window=20).mean()
    df["std_20"]  = df["close"].rolling(window=20).std()
    df["bb_width"] = (df["std_20"] * 4) / (df["sma_20"] + 1e-10)

    # Volumen promedio
    df["vol_ma"] = df["volume"].rolling(window=20).mean()

    # Filtro Macro 4H (EMA 200 sobre velas de 4 horas)
    df_temp = df.set_index("date").copy()
    close_4h = df_temp["close"].resample("4h").last()
    ema_200_4h = close_4h.ewm(span=200, adjust=False).mean().shift(1)
    df_temp["ema_macro"] = ema_200_4h.reindex(df_temp.index, method="ffill")
    df["ema_macro"] = df_temp["ema_macro"].values

    return df


def evaluar_señal(vela: dict, estado: dict) -> str:
    """
    Devuelve: COMPRAR, VENDER_*, o ESPERAR
    Usa el 100% del capital disponible en cada entrada (spot, sin leverage).
    """
    # Datos insuficientes
    if any(pd.isna(vela.get(k)) for k in ["adx", "ema_200", "ema_macro", "rsi"]):
        return "ESPERAR"

    posicion = estado["posicion"]

    # ── LÓGICA DE SALIDA ──────────────────────────────
    if posicion == "COMPRADO":
        precio_compra   = estado["precio_compra"]
        max_visto       = estado["max_precio_visto"]
        ganancia        = (vela["close"] - precio_compra) / precio_compra
        perdida_low     = (precio_compra - vela["low"]) / precio_compra
        caida_desde_max = (max_visto - vela["low"]) / (max_visto + 1e-10)

        # Stop loss fijo 7%
        if perdida_low > 0.07:
            return "VENDER_STOP_LOSS"

        # Break-even: si ganamos >5% y el precio vuelve al punto de entrada
        if ganancia > 0.05 and vela["low"] < precio_compra * 1.002:
            return "VENDER_BREAK_EVEN"

        # Trailing stop escalonado
        trailing = 0.12
        if ganancia > 0.20:
            trailing = 0.04
        elif ganancia > 0.10:
            trailing = 0.07

        if caida_desde_max > trailing:
            return "VENDER_TRAILING_STOP"

        # Cruce bajista de medias
        if vela["ema_50"] < vela["ema_200"]:
            return "VENDER_CRUCE"

        return "ESPERAR"

    # ── LÓGICA DE ENTRADA ─────────────────────────────
    if posicion == "LIQUIDO":
        tendencia_alcista   = vela["ema_50"] > vela["ema_200"]
        tendencia_macro     = vela["close"] > vela["ema_macro"]
        volumen_fuerte      = vela["volume"] > vela["vol_ma"]
        sin_sobrecompra     = vela["rsi"] < 80
        distancia_ema200    = (vela["close"] - vela["ema_200"]) / vela["ema_200"]
        precio_no_estirado  = distancia_ema200 < 0.12

        if (tendencia_alcista and tendencia_macro and volumen_fuerte
                and sin_sobrecompra and precio_no_estirado):

            adx = vela["adx"]
            if adx > 35:
                return "COMPRAR"
            elif adx > 25:
                return "COMPRAR"
            else:
                return "COMPRAR"

    return "ESPERAR"


# ══════════════════════════════════════════════════════
#  EJECUCIÓN DE ÓRDENES
# ══════════════════════════════════════════════════════

def calcular_usdt_a_usar(balance_libre: float) -> float:
    """Usa el 100% del capital disponible, igual que el simulador original en 1x."""
    usdt = min(balance_libre, CONFIG["capital_maximo_usdt"])
    return round(usdt, 2)


def ejecutar_compra(exchange, precio: float, estado: dict) -> dict:
    balance_usdt = obtener_balance_usdt(exchange)
    usdt_a_usar  = calcular_usdt_a_usar(balance_usdt)

    if usdt_a_usar < 10:
        log("⚠️  Balance insuficiente para operar (mínimo $10)")
        return estado


    if CONFIG["modo_paper"]:
        cantidad_btc = usdt_a_usar / precio
        log(f"📋 [PAPER] COMPRA: {cantidad_btc:.6f} BTC @ ${precio:,.2f} | ${usdt_a_usar:.2f}", telegram=True)
    else:
        try:
            orden = exchange.create_market_buy_order(
                CONFIG["symbol"],
                None,
                params={"quoteOrderQty": usdt_a_usar}
            )
            cantidad_btc = float(orden["filled"])
            precio       = float(orden["average"]) if orden["average"] else precio
            log(f"🟢 COMPRA REAL: {cantidad_btc:.6f} BTC @ ${precio:,.2f} | ${usdt_a_usar:.2f}", telegram=True)
        except Exception as e:
            log(f"❌ Error en orden de compra: {e}", telegram=True)
            return estado

    estado["posicion"]        = "COMPRADO"
    estado["precio_compra"]   = precio
    estado["cantidad_btc"]    = cantidad_btc if not CONFIG["modo_paper"] else usdt_a_usar / precio
    estado["usdt_en_trade"]   = usdt_a_usar
    estado["max_precio_visto"] = precio
    guardar_estado(estado)
    return estado


def ejecutar_venta(exchange, motivo: str, precio: float, estado: dict) -> dict:
    cantidad_btc = estado["cantidad_btc"]

    if CONFIG["modo_paper"]:
        usdt_recibido = cantidad_btc * precio
        pnl           = usdt_recibido - estado["usdt_en_trade"]
        emoji         = "💰" if pnl > 0 else "🔻"
        log(f"📋 [PAPER] VENTA ({motivo}): {cantidad_btc:.6f} BTC @ ${precio:.2f} | {emoji} PnL: ${pnl:.2f}", telegram=True)
    else:
        try:
            btc_libre = obtener_balance_btc(exchange)
            cantidad_vender = min(cantidad_btc, btc_libre)
            if cantidad_vender < 0.00001:
                log("⚠️  BTC insuficiente para vender")
                estado["posicion"] = "LIQUIDO"
                guardar_estado(estado)
                return estado

            orden = exchange.create_market_sell_order(CONFIG["symbol"], cantidad_vender)
            precio        = float(orden["average"]) if orden["average"] else precio
            usdt_recibido = float(orden["cost"])
            pnl           = usdt_recibido - estado["usdt_en_trade"]
            emoji         = "💰" if pnl > 0 else "🔻"
            log(f"🔴 VENTA REAL ({motivo}): {cantidad_vender:.6f} BTC @ ${precio:.2f} | {emoji} PnL: ${pnl:.2f}", telegram=True)
        except Exception as e:
            log(f"❌ Error en orden de venta: {e}", telegram=True)
            return estado

    estado["operaciones"].append({
        "fecha":         str(datetime.now()),
        "motivo":        motivo,
        "precio_compra": estado["precio_compra"],
        "precio_venta":  precio,
        "pnl_pct":       (precio - estado["precio_compra"]) / estado["precio_compra"] * 100,
    })

    estado["posicion"]        = "LIQUIDO"
    estado["precio_compra"]   = 0.0
    estado["cantidad_btc"]    = 0.0
    estado["usdt_en_trade"]   = 0.0
    estado["max_precio_visto"] = 0.0
    guardar_estado(estado)
    return estado


# ══════════════════════════════════════════════════════
#  LOOP PRINCIPAL
# ══════════════════════════════════════════════════════

def ciclo_principal(exchange, estado: dict) -> dict:
    try:
        # 1. Obtener datos frescos
        df     = obtener_velas(exchange)
        df     = generar_indicadores(df)
        precio = float(df["close"].iloc[-1])

        # Usamos la penúltima vela (ya cerrada), no la que se está formando
        vela   = df.iloc[-2].to_dict()
        vela["date"] = df.index[-2] if hasattr(df.index[-2], 'strftime') else datetime.now()

        # 2. Actualizar max_precio_visto si estamos comprados
        if estado["posicion"] == "COMPRADO":
            estado["max_precio_visto"] = max(
                estado.get("max_precio_visto", 0),
                precio
            )

        # 3. Evaluar señal
        señal = evaluar_señal(vela, estado)

        # 4. Log de estado cada ciclo
        adx_actual = vela.get("adx", 0) or 0
        rsi_actual = vela.get("rsi", 0) or 0
        log(
            f"Precio: ${precio:,.2f} | ADX: {adx_actual:.1f} | RSI: {rsi_actual:.1f} | "
            f"Posición: {estado['posicion']} | Señal: {señal}"
        )

        # 5. Ejecutar si hay señal accionable
        if "COMPRAR" in señal and estado["posicion"] == "LIQUIDO":
            estado = ejecutar_compra(exchange, precio, estado)

        elif "VENDER" in señal and estado["posicion"] == "COMPRADO":
            estado = ejecutar_venta(exchange, señal, precio, estado)

    except ccxt.NetworkError as e:
        log(f"⚠️  Error de red (reintentando): {e}")
    except ccxt.ExchangeError as e:
        log(f"⚠️  Error de exchange: {e}", telegram=True)
    except Exception as e:
        log(f"❌ Error inesperado: {e}\n{traceback.format_exc()}", telegram=True)

    return estado


def main():
    modo = "PAPER (simulación)" if CONFIG["modo_paper"] else "⚠️  REAL (dinero real)"
    log(f"════════════════════════════════════════")
    log(f"  HIDRA BOT arrancando — Modo: {modo}")
    log(f"  Par: {CONFIG['symbol']} | Capital máx: ${CONFIG['capital_maximo_usdt']}")
    log(f"════════════════════════════════════════")

    if not CONFIG["modo_paper"] and (not BINANCE_API_KEY or not BINANCE_SECRET):
        log("❌ FATAL: Faltan BINANCE_API_KEY y BINANCE_SECRET en el .env")
        return

    exchange = crear_exchange()
    estado   = cargar_estado()

    enviar_telegram(
        f"🤖 HIDRA BOT iniciado\n"
        f"Modo: {modo}\n"
        f"Par: {CONFIG['symbol']}\n"
        f"Capital máx: ${CONFIG['capital_maximo_usdt']}"
    )

    while True:
        estado = ciclo_principal(exchange, estado)
        log(f"💤 Esperando {CONFIG['intervalo_segundos']}s hasta el próximo ciclo...")
        time.sleep(CONFIG["intervalo_segundos"])


if __name__ == "__main__":
    main()