#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║         HYDRA BOT - OPTIMIZADOR MASIVO PARA KAGGLE              ║
║         Motor: Numba JIT + Optuna TPE + Joblib Parallel          ║
║         GPU: T4 x2 recomendado (usa cores CPU del nodo)          ║
╚══════════════════════════════════════════════════════════════════╝

INSTRUCCIONES KAGGLE:
  1. En Kaggle, ve a la barra lateral derecha y haz clic en "Add Data".
  2. Sube el archivo 'btc_usdt_1h.parquet' desde tu PC.
  3. Copia la ruta que te da Kaggle (ej: /kaggle/input/mi-dataset/btc_usdt_1h.parquet)
     y pégala en la variable CONFIG["archivo_datos"].
  4. Ejecutar todas las celdas.
"""

# ══════════════════════════════════════════════════════════════════
# CELDA 1 — INSTALACIÓN (ejecutar sola primero en Kaggle si hace falta)
# ══════════════════════════════════════════════════════════════════
# !pip install optuna -q

# ══════════════════════════════════════════════════════════════════
# CELDA 2 — IMPORTS Y CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════

import os
import time
import warnings
import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import numba
from numba import njit
import optuna
from optuna.samplers import TPESampler

warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ── CONFIGURACIÓN GLOBAL ────────────────────────────────────────
CONFIG = {
    # Datos
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "dias_historico": 365 * 4,          # 4 años (~35.000 velas)
    
    # ⚠️ MUY IMPORTANTE: Cambia esta ruta por la que te dé Kaggle al subir tu archivo
    "archivo_datos": "/kaggle/input/hydra-data/btc_usdt_1h.parquet",

    # Optimización
    "n_trials": 60_000,                  # Trials Optuna
    "n_jobs": 4,                         # Workers paralelos (CPU en T4 x2)
    "timeout_horas": 26,                 # Dejar 4h de margen sobre las 30h

    # Espacio de búsqueda
    "ema_fast_values": list(range(20, 85, 5)),     # 13 valores
    "ema_slow_values": list(range(100, 420, 20)),  # 16 valores
}

# ══════════════════════════════════════════════════════════════════
# CELDA 3 — CARGA DE DATOS (SIN BINANCE)
# ══════════════════════════════════════════════════════════════════

def descargar_datos() -> pd.DataFrame:
    archivo = CONFIG["archivo_datos"]

    if os.path.exists(archivo):
        print(f"✅ Cargando datos existentes desde {archivo}...")
        df = pd.read_parquet(archivo)
        
        # Asegurarnos de que las columnas están correctas por si acaso
        if "timestamp" not in df.columns and "date" in df.columns:
            df["timestamp"] = pd.to_datetime(df["date"]).astype(int) // 10**6
            
        df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.sort_values("timestamp").reset_index(drop=True)
        print(f"   {len(df):,} velas | {df['date'].iloc[0]} → {df['date'].iloc[-1]}")
        return df
    else:
        raise FileNotFoundError(f"🚨 ERROR: No se encontró el archivo de datos en {archivo}. Sube el archivo a Kaggle usando 'Add Data' y actualiza la ruta en CONFIG.")


# ══════════════════════════════════════════════════════════════════
# CELDA 4 — INDICADORES FIJOS (calculados UNA sola vez)
# ══════════════════════════════════════════════════════════════════

def _ema_numpy(arr: np.ndarray, span: int) -> np.ndarray:
    """EMA sobre array numpy puro. Rápido y compatible con numba JIT."""
    alpha = 2.0 / (span + 1)
    out = np.empty(len(arr), dtype=np.float64)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
    return out


def calcular_indicadores_fijos(df: pd.DataFrame) -> dict:
    """
    Calcula ADX, RSI, BBW, CHOP, Vol_MA, EMA_Macro, ATR.
    Estos NO dependen de parámetros → se calculan una sola vez.
    """
    print("⚙️  Pre-calculando indicadores fijos...")
    closes  = df["close"].values.astype(np.float64)
    highs   = df["high"].values.astype(np.float64)
    lows    = df["low"].values.astype(np.float64)
    volumes = df["volume"].values.astype(np.float64)
    n = len(closes)

    # ── ATR ─────────────────────────────────────────────────────
    prev_close = np.roll(closes, 1)
    prev_close[0] = closes[0]
    tr = np.maximum(highs - lows,
         np.maximum(np.abs(highs - prev_close),
                    np.abs(lows  - prev_close)))
    atr = pd.Series(tr).rolling(14).mean().values

    # ── ADX ─────────────────────────────────────────────────────
    prev_high = np.roll(highs, 1); prev_high[0] = highs[0]
    prev_low  = np.roll(lows,  1); prev_low[0]  = lows[0]
    up_move   = highs - prev_high
    down_move = prev_low - lows

    plus_dm  = np.where((up_move   > down_move) & (up_move   > 0), up_move,   0.0)
    minus_dm = np.where((down_move > up_move)   & (down_move > 0), down_move, 0.0)

    tr_s    = _ema_numpy(tr,       14)
    pdm_s   = _ema_numpy(plus_dm,  14)
    mdm_s   = _ema_numpy(minus_dm, 14)

    plus_di  = 100 * pdm_s  / (tr_s + 1e-10)
    minus_di = 100 * mdm_s  / (tr_s + 1e-10)
    dx       = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx      = _ema_numpy(dx, 14)

    # ── RSI ─────────────────────────────────────────────────────
    delta = np.diff(closes, prepend=closes[0])
    gain  = np.where(delta > 0,  delta, 0.0)
    loss  = np.where(delta < 0, -delta, 0.0)
    avg_gain = pd.Series(gain).rolling(14).mean().values
    avg_loss = pd.Series(loss).rolling(14).mean().values
    rsi = 100 - 100 / (1 + avg_gain / (avg_loss + 1e-10))

    # ── BB Width ─────────────────────────────────────────────────
    sma20   = pd.Series(closes).rolling(20).mean().values
    std20   = pd.Series(closes).rolling(20).std().values
    bb_width = (std20 * 4) / (sma20 + 1e-10)

    # ── Volume MA ─────────────────────────────────────────────────
    vol_ma = pd.Series(volumes).rolling(20).mean().values

    # ── Choppiness Index (14) ─────────────────────────────────────
    tr_sum   = pd.Series(tr).rolling(14).sum().values
    max_high = pd.Series(highs).rolling(14).max().values
    min_low  = pd.Series(lows).rolling(14).min().values
    chop     = 100 * np.log10(tr_sum / (max_high - min_low + 1e-10)) / np.log10(14)

    # ── EMA Macro (≈ EMA 200 en 4h → equivale a EMA 800 en 1h) ──
    ema_macro = _ema_numpy(closes, 800)

    print(f"✅ Indicadores fijos listos para {n:,} velas")
    return dict(closes=closes, highs=highs, lows=lows, volumes=volumes,
                atr=atr, adx=adx, rsi=rsi, bb_width=bb_width,
                vol_ma=vol_ma, chop=chop, ema_macro=ema_macro)


# ══════════════════════════════════════════════════════════════════
# CELDA 5 — CACHÉ DE EMAs PARAMETRIZADAS
# ══════════════════════════════════════════════════════════════════

_ema_cache: dict = {}   # {span: np.ndarray}


def precalentar_ema_cache(closes: np.ndarray) -> None:
    """
    Pre-calcula las 13+16=29 EMAs candidatas y las guarda en RAM.
    Se tarda ~2 segundos. Evita recalcular durante la optimización.
    """
    print("🔥 Pre-calculando caché de EMAs...")
    spans = set(CONFIG["ema_fast_values"]) | set(CONFIG["ema_slow_values"])
    for s in sorted(spans):
        _ema_cache[s] = _ema_numpy(closes, s)
    print(f"✅ {len(_ema_cache)} EMAs pre-calculadas en RAM")


def get_ema(span: int) -> np.ndarray:
    """Recupera EMA del caché (o la calcula si no existe)."""
    if span not in _ema_cache:
        # No debería pasar después del pre-calentamiento, pero por si acaso
        _ema_cache[span] = _ema_numpy(_IND["closes"], span)
    return _ema_cache[span]


# ══════════════════════════════════════════════════════════════════
# CELDA 6 — BACKTEST CORE (NUMBA JIT)
# ══════════════════════════════════════════════════════════════════

@njit(cache=True, fastmath=True)
def backtest_numba(
    closes, highs, lows, volumes,
    ema_fast, ema_slow,
    adx, rsi, bb_width, chop, vol_ma, ema_macro, atr,
    # ── Parámetros de optimización ──────────────────────────────
    umbral_adx: float,          # Fuerza mínima de tendencia
    stop_loss_pct: float,       # Stop loss porcentual
    umbral_bbw: float,          # Cap de volatilidad BB
    umbral_chop: float,         # Umbral de lateralidad
    trailing_base: float,       # Trailing por defecto
    trailing_2: float,          # Trailing con ganancia >10%
    trailing_1: float,          # Trailing con ganancia >20%
    breakeven_trigger: float,   # Ganancia mínima para break-even
) -> tuple:
    """
    Motor de backtesting compilado a código nativo con Numba JIT.
    """
    balance          = 1_000.0
    posicion         = 0        # 0=sin posición, 1=comprado
    precio_compra    = 0.0
    max_precio_visto = 0.0
    leverage         = 1.0
    comision         = 0.001

    total_ops  = 0
    wins       = 0
    max_bal    = 1_000.0
    max_dd     = 0.0

    n = len(closes)

    for i in range(n):
        # Skip si indicadores NaN (inicio de la serie)
        if (adx[i] != adx[i] or ema_slow[i] != ema_slow[i] or
                ema_macro[i] != ema_macro[i] or bb_width[i] != bb_width[i]):
            continue

        c = closes[i]
        h = highs[i]
        l = lows[i]
        v = volumes[i]

        # ── GESTIÓN DE POSICIÓN ABIERTA ──────────────────────────
        if posicion == 1:
            if h > max_precio_visto:
                max_precio_visto = h

            perdida       = (precio_compra - l) / precio_compra
            ganancia      = (c - precio_compra) / precio_compra
            caida_max     = (max_precio_visto - l) / max_precio_visto
            resultado     = 0.0
            vender        = False

            # 1. Liquidación forzada
            liq_umbral = 0.9 / leverage
            if perdida > liq_umbral:
                resultado = -0.9
                vender = True

            # 2. Stop Loss
            elif perdida > stop_loss_pct:
                resultado = (c - precio_compra) / precio_compra * leverage
                vender = True

            # 3. Break Even (si ganamos > trigger y precio cae al costo)
            elif ganancia > breakeven_trigger and l < precio_compra * 1.002:
                resultado = 0.0
                vender = True

            # 4. Trailing escalonado
            elif caida_max > (trailing_1 if ganancia > 0.20 else
                              trailing_2 if ganancia > 0.10 else trailing_base):
                resultado = (c - precio_compra) / precio_compra * leverage
                vender = True

            # 5. Cruce EMA bajista
            elif ema_fast[i] <= ema_slow[i]:
                resultado = (c - precio_compra) / precio_compra * leverage
                vender = True

            if vender:
                balance   = balance * (1.0 + resultado) * (1.0 - comision)
                posicion  = 0
                total_ops += 1
                if resultado > 0.0:
                    wins += 1
                # Actualizar max drawdown
                if balance > max_bal:
                    max_bal = balance
                dd = (max_bal - balance) / max_bal
                if dd > max_dd:
                    max_dd = dd

        # ── BÚSQUEDA DE ENTRADA ───────────────────────────────────
        else:
            max_precio_visto = 0.0

            tendencia_ok = ema_fast[i] > ema_slow[i]
            macro_ok     = c > ema_macro[i]
            vol_ok       = v > vol_ma[i]
            rsi_ok       = rsi[i] <= 80.0
            bbw_ok       = bb_width[i] <= umbral_bbw
            chop_ok      = chop[i] <= umbral_chop
            adx_ok       = adx[i] > umbral_adx
            dist_ok      = (c - ema_slow[i]) / ema_slow[i] <= 0.12  # Filtro elástico

            if tendencia_ok and macro_ok and vol_ok and rsi_ok and bbw_ok and chop_ok and adx_ok and dist_ok:
                # Leverage dinámico por volatilidad ATR
                vol_atr  = atr[i] / (c + 1e-10)
                mult_vol = 0.5 if vol_atr > 0.04 else (0.8 if vol_atr > 0.02 else 1.0)

                if adx[i] > 35.0:
                    leverage = round(1.5 * mult_vol * 10.0) / 10.0
                elif adx[i] > umbral_adx:
                    leverage = round(1.2 * mult_vol * 10.0) / 10.0
                else:
                    leverage = round(1.0 * mult_vol * 10.0) / 10.0

                balance       = balance * (1.0 - comision)
                precio_compra = c
                max_precio_visto = c
                posicion      = 1

    win_rate = wins / total_ops if total_ops > 0 else 0.0
    return balance, total_ops, win_rate, max_dd * 100.0


# ══════════════════════════════════════════════════════════════════
# CELDA 7 — FUNCIÓN OBJETIVO OPTUNA
# ══════════════════════════════════════════════════════════════════

# Variables globales compartidas entre workers
_IND: dict = {}

def objective(trial: optuna.Trial) -> float:
    # ── Sugerir parámetros ────────────────────────────────────────
    ema_fast_span = trial.suggest_categorical("ema_fast", CONFIG["ema_fast_values"])
    ema_slow_span = trial.suggest_categorical("ema_slow", CONFIG["ema_slow_values"])

    if ema_fast_span >= ema_slow_span:
        raise optuna.exceptions.TrialPruned()

    umbral_adx      = trial.suggest_float("adx",        15.0,  45.0, step=5.0)
    stop_loss_pct   = trial.suggest_float("stop_loss",   0.03,  0.12, step=0.01)
    umbral_bbw      = trial.suggest_float("bbw",         0.05,  0.20, step=0.01)
    umbral_chop     = trial.suggest_float("chop",        40.0,  70.0, step=5.0)
    trailing_base   = trial.suggest_float("trail_base",  0.06,  0.20, step=0.01)
    trailing_2      = trial.suggest_float("trail_2",     0.03,  0.12, step=0.01)
    trailing_1      = trial.suggest_float("trail_1",     0.02,  0.08, step=0.01)
    breakeven       = trial.suggest_float("breakeven",   0.02,  0.10, step=0.01)

    if not (trailing_1 < trailing_2 < trailing_base):
        raise optuna.exceptions.TrialPruned()

    # ── Ejecutar backtest ─────────────────────────────────────────
    ind = _IND
    balance, ops, win_rate, max_dd = backtest_numba(
        ind["closes"], ind["highs"], ind["lows"], ind["volumes"],
        get_ema(ema_fast_span), get_ema(ema_slow_span),
        ind["adx"], ind["rsi"], ind["bb_width"], ind["chop"],
        ind["vol_ma"], ind["ema_macro"], ind["atr"],
        umbral_adx, stop_loss_pct, umbral_bbw, umbral_chop,
        trailing_base, trailing_2, trailing_1, breakeven,
    )

    # ── Filtros de calidad mínima ─────────────────────────────────
    if ops < 15:
        raise optuna.exceptions.TrialPruned()
    if max_dd > 70.0:
        raise optuna.exceptions.TrialPruned()

    # ── Calcular score ────────────────────────────────────────────
    beneficio_pct = (balance - 1_000.0) / 1_000.0 * 100.0
    calmar = beneficio_pct / (max_dd + 1e-6)
    score = calmar * (win_rate ** 0.4)

    # ── Guardar métricas extra para análisis ──────────────────────
    trial.set_user_attr("balance",      round(balance, 2))
    trial.set_user_attr("beneficio_%",  round(beneficio_pct, 2))
    trial.set_user_attr("ops",          ops)
    trial.set_user_attr("win_rate_%",   round(win_rate * 100, 2))
    trial.set_user_attr("max_dd_%",     round(max_dd, 2))
    trial.set_user_attr("calmar",       round(calmar, 4))

    return score


# ══════════════════════════════════════════════════════════════════
# CELDA 8 — ANÁLISIS Y EXPORTACIÓN DE RESULTADOS
# ══════════════════════════════════════════════════════════════════

def exportar_resultados(study: optuna.Study, top_n: int = 30) -> pd.DataFrame:
    df_trials = study.trials_dataframe()
    df_ok = df_trials[df_trials["state"] == "COMPLETE"].copy()

    if df_ok.empty:
        print("⚠️  No hay trials completados para exportar.")
        return df_ok

    rename = {
        "params_ema_fast":  "EMA_Rapida",
        "params_ema_slow":  "EMA_Lenta",
        "params_adx":       "ADX_Umbral",
        "params_stop_loss": "Stop_Loss",
        "params_bbw":       "BBW_Umbral",
        "params_chop":      "CHOP_Umbral",
        "params_trail_base":"Trail_Base",
        "params_trail_2":   "Trail_Gain10",
        "params_trail_1":   "Trail_Gain20",
        "params_breakeven": "BreakEven",
        "user_attrs_balance":     "Balance_Final",
        "user_attrs_beneficio_%": "Beneficio_%",
        "user_attrs_ops":         "Operaciones",
        "user_attrs_win_rate_%":  "Win_Rate_%",
        "user_attrs_max_dd_%":    "Max_DD_%",
        "user_attrs_calmar":      "Calmar_Ratio",
        "value":                  "Score_Optuna",
    }
    df_ok = df_ok.rename(columns=rename)

    cols_interes = [c for c in rename.values() if c in df_ok.columns]
    df_top = df_ok.nlargest(top_n, "Score_Optuna")[cols_interes].reset_index(drop=True)
    df_top.index += 1

    path_top    = "/kaggle/working/top30_configuraciones.csv"
    path_todos  = "/kaggle/working/todos_los_trials.csv"
    path_report = "/kaggle/working/reporte_optimizacion.txt"

    df_top.to_csv(path_top, index_label="Rank")
    df_ok.nlargest(len(df_ok), "Score_Optuna").to_csv(path_todos, index=False)

    mejor = study.best_trial
    lineas = [
        "═" * 70,
        "  HYDRA BOT — REPORTE DE OPTIMIZACIÓN MASIVA",
        "═" * 70,
        f"  Trials completados : {len(df_ok):,}",
        f"  Mejor Score Optuna : {study.best_value:.4f}",
        "",
        "  🥇 MEJOR CONFIGURACIÓN ENCONTRADA:",
        "  " + "─" * 50,
    ]
    for k, v in study.best_params.items():
        lineas.append(f"    {k:<20}: {v}")
    lineas += [
        "  " + "─" * 50,
        f"    Balance Final     : ${mejor.user_attrs.get('balance', 0):,.2f}",
        f"    Beneficio Neto    : {mejor.user_attrs.get('beneficio_%', 0):.2f}%",
        f"    Win Rate          : {mejor.user_attrs.get('win_rate_%', 0):.2f}%",
        f"    Max Drawdown      : {mejor.user_attrs.get('max_dd_%', 0):.2f}%",
        f"    Operaciones       : {mejor.user_attrs.get('ops', 0)}",
        "",
        f"  TOP {top_n} guardado en: {path_top}",
        "═" * 70,
    ]

    with open(path_report, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))

    print("\n".join(lineas))
    return df_top


# ══════════════════════════════════════════════════════════════════
# CELDA 9 — MAIN (PUNTO DE ENTRADA)
# ══════════════════════════════════════════════════════════════════

def main():
    global _IND

    print("╔══════════════════════════════════════════════════════╗")
    print("║     HYDRA BOT — OPTIMIZADOR MASIVO KAGGLE           ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    # ── 1. Cargar datos locales ────────────────────────────
    df = descargar_datos()

    # ── 2. Calcular indicadores fijos ────────────
    _IND = calcular_indicadores_fijos(df)

    # ── 3. Pre-calentar caché de EMAs ──────────────────────────
    precalentar_ema_cache(_IND["closes"])

    # ── 4. Warm-up de Numba ────
    print("🔥 Compilando Numba JIT (tardará ~30 segundos)...")
    t0 = time.time()
    _ = backtest_numba(
        _IND["closes"], _IND["highs"], _IND["lows"], _IND["volumes"],
        get_ema(50), get_ema(200),
        _IND["adx"], _IND["rsi"], _IND["bb_width"], _IND["chop"],
        _IND["vol_ma"], _IND["ema_macro"], _IND["atr"],
        25.0, 0.07, 0.12, 55.0, 0.12, 0.07, 0.04, 0.05,
    )
    print(f"✅ Numba compilado en {time.time()-t0:.1f}s\n")

    # ── 5. Crear estudio Optuna ───────
    sampler = TPESampler(n_startup_trials=500, seed=42, multivariate=True)
    study = optuna.create_study(
        direction="maximize",
        sampler=sampler,
        study_name="hydra_v5_optimization",
        storage="sqlite:////kaggle/working/hydra_optuna.db",
        load_if_exists=True,
    )

    # ── 6. Callback de progreso ─────────────────
    def callback_progreso(study, trial):
        if trial.number % 500 == 0 and trial.number > 0:
            completados = len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE])
            mejor = study.best_value
            best_b = study.best_trial.user_attrs.get("balance", 0)
            best_dd = study.best_trial.user_attrs.get("max_dd_%", 0)
            print(f"  [Trial {trial.number:>6}] Completados: {completados:,} | Mejor Balance: ${best_b:,.0f} | DD: {best_dd:.1f}%")

    # ── 7. Lanzar optimización ───────────────────────────────────
    print("🚀 OPTIMIZACIÓN INICIANDO...")
    inicio = time.time()
    study.optimize(
        objective,
        n_trials=CONFIG["n_trials"],
        timeout=CONFIG["timeout_horas"] * 3600,
        n_jobs=CONFIG["n_jobs"],
        callbacks=[callback_progreso],
        gc_after_trial=False,
        show_progress_bar=False,
    )
    elapsed = time.time() - inicio

    print(f"\n✅ OPTIMIZACIÓN COMPLETADA EN {elapsed/3600:.2f} HORAS\n")

    # ── 8. Exportar resultados ───────────────────────────────────
    df_top = exportar_resultados(study, top_n=30)
    return study, df_top


if __name__ == "__main__":
    study, df_top = main()
    print("\n🏆 TOP 10 CONFIGURACIONES (por Score):")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    print(df_top.head(10).to_string())
