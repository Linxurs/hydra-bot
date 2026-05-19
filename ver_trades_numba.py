#!/usr/bin/env python3
import os
import time
import warnings
import numpy as np
import pandas as pd
from numba import njit
from datetime import datetime
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

ARCHIVO_IS = "datos/btc_usdt_1h.parquet"

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
def backtest_numba_verbose(
    closes, highs, lows, volumes, ema_fast, ema_slow, adx, rsi, bb_width, chop, vol_ma, ema_macro, atr,
    umbral_adx, stop_loss_pct, umbral_bbw, umbral_chop, trailing_base, trailing_2, trailing_1, breakeven_trigger,
    out_idx, out_type, out_price, out_pnl, out_balance, out_lev
):
    balance = 1_000.0
    posicion = 0; precio_compra = 0.0; max_precio_visto = 0.0
    leverage = 1.0; comision = 0.001
    total_ops = 0; wins = 0; max_bal = 1_000.0; max_dd = 0.0
    
    ptr = 0 # Puntero para escribir en los arrays de salida

    for i in range(len(closes)):
        if adx[i] != adx[i] or ema_slow[i] != ema_slow[i] or ema_macro[i] != ema_macro[i]: continue
        c = closes[i]; h = highs[i]; l = lows[i]; v = volumes[i]

        if posicion == 1:
            if h > max_precio_visto: max_precio_visto = h
            perdida   = (precio_compra - l) / precio_compra
            ganancia  = (c - precio_compra) / precio_compra
            caida_max = (max_precio_visto - l) / max_precio_visto
            resultado = 0.0; vender = False
            
            tipo_salida = 0 # 1: LIQ, 2: SL, 3: BE, 4: TS, 5: EMA

            if   perdida > 0.9 / leverage: resultado = -0.9; vender = True; tipo_salida = 1
            elif perdida > stop_loss_pct: resultado = (c - precio_compra) / precio_compra * leverage; vender = True; tipo_salida = 2
            elif ganancia > breakeven_trigger and l < precio_compra * 1.002: resultado = 0.0; vender = True; tipo_salida = 3
            elif caida_max > (trailing_1 if ganancia > 0.20 else trailing_2 if ganancia > 0.10 else trailing_base):
                resultado = (c - precio_compra) / precio_compra * leverage; vender = True; tipo_salida = 4
            elif ema_fast[i] <= ema_slow[i]: resultado = (c - precio_compra) / precio_compra * leverage; vender = True; tipo_salida = 5

            if vender:
                pnl_usd = balance * resultado
                balance = balance * (1.0 + resultado) * (1.0 - comision)
                posicion = 0; total_ops += 1
                if resultado > 0.0: wins += 1
                if balance > max_bal: max_bal = balance
                dd = (max_bal - balance) / max_bal
                if dd > max_dd: max_dd = dd
                
                # Registrar Venta
                out_idx[ptr] = i
                out_type[ptr] = -tipo_salida
                out_price[ptr] = c
                out_pnl[ptr] = pnl_usd
                out_balance[ptr] = balance
                out_lev[ptr] = leverage
                ptr += 1
                
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
                
                # Registrar Compra
                out_idx[ptr] = i
                out_type[ptr] = 1 # 1 = Compra
                out_price[ptr] = c
                out_pnl[ptr] = 0.0
                out_balance[ptr] = balance
                out_lev[ptr] = leverage
                ptr += 1
                
        if balance > max_bal: max_bal = balance
    return balance, total_ops, (wins / total_ops if total_ops > 0 else 0.0), max_dd * 100.0, ptr

def mostrar_magia():
    print("📂 Cargando motor Numba y datos In-Sample...")
    df_is = pd.read_parquet(ARCHIVO_IS)
    fechas = pd.to_datetime(df_is["timestamp"], unit="ms").dt.strftime('%y-%m-%d %H:%M').values
    
    # Parámetros Exactos del Top 1 de Kaggle
    ema_f = 25
    ema_s = 100
    adx = 40.0
    sl = 0.07
    bbw = 0.14
    chop = 60.0
    tr_b = 0.12
    tr_2 = 0.10
    tr_1 = 0.02
    be = 0.10

    ind = calcular_indicadores(df_is, ema_f, ema_s)
    
    # Arrays pre-reservados para Numba (asumimos max 5000 operaciones)
    max_events = 5000
    out_idx = np.zeros(max_events, dtype=np.int64)
    out_type = np.zeros(max_events, dtype=np.int64)
    out_price = np.zeros(max_events, dtype=np.float64)
    out_pnl = np.zeros(max_events, dtype=np.float64)
    out_balance = np.zeros(max_events, dtype=np.float64)
    out_lev = np.zeros(max_events, dtype=np.float64)

    # Warmup
    _ = backtest_numba_verbose(
        ind["closes"][:1000], ind["highs"][:1000], ind["lows"][:1000], ind["volumes"][:1000], 
        ind["ema_fast"][:1000], ind["ema_slow"][:1000], ind["adx"][:1000], ind["rsi"][:1000], 
        ind["bb_width"][:1000], ind["chop"][:1000], ind["vol_ma"][:1000], ind["ema_macro"][:1000], ind["atr"][:1000], 
        adx, sl, bbw, chop, tr_b, tr_2, tr_1, be,
        out_idx, out_type, out_price, out_pnl, out_balance, out_lev
    )

    print("\n🚀 Ejecutando Simulación Exacta (100% Matemática Numba)...\n")
    
    bal, ops, wr, dd, ptr = backtest_numba_verbose(
        ind["closes"], ind["highs"], ind["lows"], ind["volumes"], 
        ind["ema_fast"], ind["ema_slow"], ind["adx"], ind["rsi"], 
        ind["bb_width"], ind["chop"], ind["vol_ma"], ind["ema_macro"], ind["atr"], 
        adx, sl, bbw, chop, tr_b, tr_2, tr_1, be,
        out_idx, out_type, out_price, out_pnl, out_balance, out_lev
    )

    print("="*100)
    print(f"{'FECHA':<18} | {'TIPO':<10} | {'PRECIO':<9} | {'RESULTADO':<15} | {'BALANCE'}")
    print("="*100)
    
    razones = {
        -1: "LIQUIDADO",
        -2: "STOP LOSS",
        -3: "BREAK EVEN",
        -4: "TRAILING",
        -5: "CRUCE EMA"
    }

    # Mostrar solo el último 10% de los trades para no saturar la consola, y el final
    mostrar_desde = max(0, ptr - 150)
    
    for i in range(mostrar_desde, ptr):
        idx = out_idx[i]
        tipo = out_type[i]
        
        fecha = fechas[idx]
        precio = out_price[i]
        balance = out_balance[i]
        leverage = out_lev[i]
        
        if tipo == 1:
            print(f"{fecha:<18} | C {leverage}x     | ${precio:<8.0f} | {'---':<15} | ${balance:,.2f}")
        else:
            pnl = out_pnl[i]
            motivo = razones.get(tipo, "VENTA")
            color = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
            print(f"{fecha:<18} | VENTA ({motivo[:4]})| ${precio:<8.0f} | {color} ${pnl:<12,.1f} | ${balance:,.2f}")

    print("\n" + "="*50)
    print("  REPORTE FINAL: SANTO GRIAL (NUMBA EXACTO)")
    print("-" * 50)
    print(f"  Balance Final:      ${bal:,.2f}")
    print(f"  Beneficio Neto:     {((bal-1000)/1000)*100:.2f}%")
    print(f"  Max Drawdown:       -{dd:.2f}%")
    print(f"  Win Rate:           {wr*100:.2f}%")
    print(f"  Operaciones:        {ops}")
    print("="*50)

    # --- LÓGICA DE GRÁFICADO ---
    print("\n--- [GRAFICADOR] Generando visualización INTERACTIVA PRO... ---")
    print("📈 Ventana Abierta. USA EL SCROLL PARA ZOOM Y ARRASTRA PARA MOVER.")
    
    fig, ax = plt.subplots(figsize=(16, 8))
    fig.patch.set_facecolor('#0a0a0a')
    ax.set_facecolor('#0a0a0a')
    
    # Preparar datos de ploteo
    fechas_pd = pd.to_datetime(df_is["timestamp"], unit="ms")
    ax.plot(fechas_pd, df_is["close"], label="Precio BTC", color="#333333", alpha=0.6, linewidth=1)
    ax.plot(fechas_pd, ind["ema_fast"], label="EMA 25 (Rápida)", color="#004400", alpha=0.8, linewidth=1.5)
    ax.plot(fechas_pd, ind["ema_slow"], label="EMA 100 (Lenta)", color="#440044", alpha=0.8, linewidth=1.5)
    
    compras_x, compras_y = [], []
    ventas_x, ventas_y, ventas_c = [], [], []
    
    for i in range(ptr):
        idx = out_idx[i]
        if out_type[i] == 1:
            compras_x.append(fechas_pd[idx])
            compras_y.append(out_price[i])
        else:
            ventas_x.append(fechas_pd[idx])
            ventas_y.append(out_price[i])
            ventas_c.append("#006400" if out_pnl[i] > 0 else "#8b0000")
            
    ax.scatter(compras_x, compras_y, marker="^", color="#ffffff", s=100, edgecolors="gray", zorder=5, label="COMPRA")
    ax.scatter(ventas_x, ventas_y, marker="v", c=ventas_c, s=100, edgecolors="#111111", zorder=5, label="VENTA (Verde=Win, Rojo=Loss)")
    
    ax.set_title("HYDRA-BOT: SANTO GRIAL (650k) | SCROLL=Zoom CLICK-IZQ=Mover", fontsize=14, color="gray")
    ax.legend(loc="upper left")
    ax.grid(color="#111111", linestyle="--", alpha=0.5)
    
    def zoom(event):
        base_scale = 1.5
        cur_xlim = ax.get_xlim()
        cur_ylim = ax.get_ylim()
        xdata = event.xdata
        ydata = event.ydata
        if xdata is None or ydata is None: return
        scale_factor = 1 / base_scale if event.button == "up" else base_scale if event.button == "down" else 1
        new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor
        relx = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])
        rely = (cur_ylim[1] - ydata) / (cur_ylim[1] - cur_ylim[0])
        ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * relx])
        ax.set_ylim([ydata - new_height * (1 - rely), ydata + new_height * rely])
        plt.draw()

    fig.canvas.mpl_connect("scroll_event", zoom)
    plt.show()

if __name__ == "__main__":
    mostrar_magia()