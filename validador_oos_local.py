#!/usr/bin/env python3
import os
import time
import warnings
import numpy as np
import pandas as pd
from numba import njit
from datetime import datetime, timezone
import ccxt

warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════════════════════
# CONFIGURACIÓN LOCAL
# ══════════════════════════════════════════════════════════════════

ARCHIVO_IS      = "datos/btc_usdt_1h.parquet"
ARCHIVO_OOS     = "datos/btc_usdt_1h_oos.parquet"
ARCHIVO_TOP30   = "top30_configuraciones.csv"
FECHA_CORTE_OOS = "2026-02-23 03:00:00"
TOP_N           = 10

# ══════════════════════════════════════════════════════════════════
# FUNCIONES (Iguales a tu script, pero rutas adaptadas)
# ══════════════════════════════════════════════════════════════════

def descargar_datos_frescos() -> pd.DataFrame:
    if os.path.exists(ARCHIVO_OOS):
        print(f"✅ Datos OOS locales encontrados...")
        df = pd.read_parquet(ARCHIVO_OOS)
        df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df

    print("📥 Descargando datos frescos desde Binance (Local)...")
    exchange = ccxt.binance({"enableRateLimit": True})
    since_ms = int(datetime.strptime(FECHA_CORTE_OOS, "%Y-%m-%d %H:%M:%S")
                   .replace(tzinfo=timezone.utc).timestamp() * 1000) + 3_600_000

    all_candles = []
    
    while True:
        try:
            candles = exchange.fetch_ohlcv("BTC/USDT", "1h", since_ms, 1000)
            if not candles: break
            all_candles.extend(candles)
            since_ms = candles[-1][0] + 1
            if candles[-1][0] >= exchange.milliseconds() - 3_600_000: break
            time.sleep(0.5)
        except Exception as e:
            print(f"Error: {e}. Reintentando en 5s...")
            time.sleep(5)

    print(f"✅ {len(all_candles):,} velas frescas descargadas")
    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.to_parquet(ARCHIVO_OOS)
    return df

def _ema_numpy(arr: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1)
    out = np.empty(len(arr), dtype=np.float64)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
    return out

def calcular_indicadores(df: pd.DataFrame, ema_fast_span: int, ema_slow_span: int) -> dict:
    closes  = df["close"].values.astype(np.float64)
    highs   = df["high"].values.astype(np.float64)
    lows    = df["low"].values.astype(np.float64)
    volumes = df["volume"].values.astype(np.float64)

    prev_c = np.roll(closes, 1); prev_c[0] = closes[0]
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_c), np.abs(lows - prev_c)))
    atr = pd.Series(tr).rolling(14).mean().values

    prev_h = np.roll(highs, 1); prev_h[0] = highs[0]
    prev_l = np.roll(lows,  1); prev_l[0] = lows[0]
    plus_dm  = np.where((highs - prev_h > prev_l - lows) & (highs - prev_h > 0), highs - prev_h, 0.0)
    minus_dm = np.where((prev_l - lows > highs - prev_h) & (prev_l - lows > 0), prev_l - lows, 0.0)
    tr_s     = _ema_numpy(tr, 14)
    plus_di  = 100 * _ema_numpy(plus_dm,  14) / (tr_s + 1e-10)
    minus_di = 100 * _ema_numpy(minus_dm, 14) / (tr_s + 1e-10)
    adx      = _ema_numpy(100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10), 14)

    delta    = np.diff(closes, prepend=closes[0])
    avg_gain = pd.Series(np.where(delta > 0,  delta, 0.0)).rolling(14).mean().values
    avg_loss = pd.Series(np.where(delta < 0, -delta, 0.0)).rolling(14).mean().values
    rsi      = 100 - 100 / (1 + avg_gain / (avg_loss + 1e-10))

    sma20    = pd.Series(closes).rolling(20).mean().values
    bb_width = (pd.Series(closes).rolling(20).std().values * 4) / (sma20 + 1e-10)
    vol_ma   = pd.Series(volumes).rolling(20).mean().values

    tr_sum   = pd.Series(tr).rolling(14).sum().values
    chop     = 100 * np.log10(tr_sum / (pd.Series(highs).rolling(14).max().values - pd.Series(lows).rolling(14).min().values + 1e-10)) / np.log10(14)

    return dict(
        closes=closes, highs=highs, lows=lows, volumes=volumes,
        atr=atr, adx=adx, rsi=rsi, bb_width=bb_width, vol_ma=vol_ma, chop=chop,
        ema_macro=_ema_numpy(closes, 800), ema_fast=_ema_numpy(closes, ema_fast_span), ema_slow=_ema_numpy(closes, ema_slow_span)
    )

@njit(cache=True, fastmath=True)
def backtest_numba(closes, highs, lows, volumes, ema_fast, ema_slow, adx, rsi, bb_width, chop, vol_ma, ema_macro, atr,
                   umbral_adx, stop_loss_pct, umbral_bbw, umbral_chop, trailing_base, trailing_2, trailing_1, breakeven_trigger) -> tuple:
    balance = 1_000.0
    posicion = 0; precio_compra = 0.0; max_precio_visto = 0.0
    leverage = 1.0; comision = 0.001
    total_ops = 0; wins = 0; max_bal = 1_000.0; max_dd = 0.0

    for i in range(len(closes)):
        if adx[i] != adx[i] or ema_slow[i] != ema_slow[i] or ema_macro[i] != ema_macro[i]: continue
        c = closes[i]; h = highs[i]; l = lows[i]; v = volumes[i]

        if posicion == 1:
            if h > max_precio_visto: max_precio_visto = h
            perdida   = (precio_compra - l) / precio_compra
            ganancia  = (c - precio_compra) / precio_compra
            caida_max = (max_precio_visto - l) / max_precio_visto
            resultado = 0.0; vender = False

            if   perdida > 0.9 / leverage: resultado = -0.9; vender = True
            elif perdida > stop_loss_pct: resultado = (c - precio_compra) / precio_compra * leverage; vender = True
            elif ganancia > breakeven_trigger and l < precio_compra * 1.002: resultado = 0.0; vender = True
            elif caida_max > (trailing_1 if ganancia > 0.20 else trailing_2 if ganancia > 0.10 else trailing_base):
                resultado = (c - precio_compra) / precio_compra * leverage; vender = True
            elif ema_fast[i] <= ema_slow[i]: resultado = (c - precio_compra) / precio_compra * leverage; vender = True

            if vender:
                balance = balance * (1.0 + resultado) * (1.0 - comision)
                posicion = 0; total_ops += 1
                if resultado > 0.0: wins += 1
                if balance > max_bal: max_bal = balance
                dd = (max_bal - balance) / max_bal
                if dd > max_dd: max_dd = dd
        else:
            max_precio_visto = 0.0
            if (ema_fast[i] > ema_slow[i] and c > ema_macro[i] and v > vol_ma[i] and rsi[i] <= 80.0 and 
                bb_width[i] <= umbral_bbw and chop[i] <= umbral_chop and adx[i] > umbral_adx and 
                (c - ema_slow[i]) / ema_slow[i] <= 0.12):
                vol_atr  = atr[i] / (c + 1e-10)
                mult_vol = 0.5 if vol_atr > 0.04 else (0.8 if vol_atr > 0.02 else 1.0)
                leverage = (round(1.5 * mult_vol * 10) / 10 if adx[i] > 35.0 else
                            round(1.2 * mult_vol * 10) / 10 if adx[i] > umbral_adx else
                            round(1.0 * mult_vol * 10) / 10)
                balance = balance * (1.0 - comision); precio_compra = c; max_precio_visto = c; posicion = 1
        if balance > max_bal: max_bal = balance
    return balance, total_ops, (wins / total_ops if total_ops > 0 else 0.0), max_dd * 100.0

def validar_oos_real():
    print("📂 Cargando datos locales...")
    df_is  = pd.read_parquet(ARCHIVO_IS)
    df_oos = pd.read_parquet(ARCHIVO_OOS)
    
    if not os.path.exists(ARCHIVO_TOP30):
        print(f"❌ Falta el archivo {ARCHIVO_TOP30}. Descárgalo de Kaggle y ponlo en esta carpeta.")
        return

    df_top = pd.read_csv(ARCHIVO_TOP30).head(TOP_N)
    
    # Warm-up Numba
    print("🔥 Compilando Numba...")
    _ind = calcular_indicadores(df_is.head(1000), 50, 200)
    _ = backtest_numba(_ind["closes"], _ind["highs"], _ind["lows"], _ind["volumes"], _ind["ema_fast"], _ind["ema_slow"], _ind["adx"], _ind["rsi"], _ind["bb_width"], _ind["chop"], _ind["vol_ma"], _ind["ema_macro"], _ind["atr"], 25.0, 0.07, 0.12, 55.0, 0.12, 0.07, 0.04, 0.05)
    
    print(f"\n{'Rank':<5} {'EMA':<7} │ {'IS Ret%':>9} {'IS DD%':>7} │ {'OOS Ret%':>9} {'OOS DD%':>7} │ {'Veredicto'}")
    print("-" * 80)

    for rank, row in df_top.iterrows():
        def get(a, b, default): return float(row.get(a, row.get(b, default)))
        args = (get("ADX_Umbral", "params_adx", 25), get("Stop_Loss", "params_stop_loss", 0.07), get("BBW_Umbral", "params_bbw", 0.12), get("CHOP_Umbral", "params_chop", 55), get("Trail_Base", "params_trail_base", 0.12), get("Trail_Gain10", "params_trail_2", 0.07), get("Trail_Gain20", "params_trail_1", 0.04), get("BreakEven", "params_breakeven", 0.05))
        
        ind = calcular_indicadores(df_is, int(get("EMA_Rapida", "params_ema_fast", 50)), int(get("EMA_Lenta", "params_ema_slow", 200)))
        bal_is, _, _, dd_is = backtest_numba(ind["closes"], ind["highs"], ind["lows"], ind["volumes"], ind["ema_fast"], ind["ema_slow"], ind["adx"], ind["rsi"], ind["bb_width"], ind["chop"], ind["vol_ma"], ind["ema_macro"], ind["atr"], *args)
        ret_is = (bal_is - 1000) / 1000 * 100
        
        ind_oos = calcular_indicadores(df_oos, int(get("EMA_Rapida", "params_ema_fast", 50)), int(get("EMA_Lenta", "params_ema_slow", 200)))
        bal_oos, _, _, dd_oos = backtest_numba(ind_oos["closes"], ind_oos["highs"], ind_oos["lows"], ind_oos["volumes"], ind_oos["ema_fast"], ind_oos["ema_slow"], ind_oos["adx"], ind_oos["rsi"], ind_oos["bb_width"], ind_oos["chop"], ind_oos["vol_ma"], ind_oos["ema_macro"], ind_oos["atr"], *args)
        ret_oos = (bal_oos - 1000) / 1000 * 100

        veredicto = "✅ ROBUSTO" if bal_oos > 1000 and ret_oos > ret_is * 0.25 else "⚠️  DÉBIL" if bal_oos > 1000 else "❌ OVERFIT"
        print(f"{rank+1:<5} {int(get('EMA_Rapida', 'params_ema_fast', 50))}/{int(get('EMA_Lenta', 'params_ema_slow', 200)):<5} │ {ret_is:>8.1f}% {dd_is:>6.1f}% │ {ret_oos:>8.1f}% {dd_oos:>6.1f}% │ {veredicto}")

if __name__ == "__main__":
    descargar_datos_frescos()
    validar_oos_real()
