import pandas as pd
import numpy as np
from itertools import product
from joblib import Parallel, delayed
import time

# ==========================================
# MOTOR DE CÁLCULO ULTRA-RÁPIDO (NUMPY)
# ==========================================

def simulacion_core(closes, lows, highs, adx, bbw, rsi, ema_fast, ema_slow, p):
    """
    Simulación pura usando arrays de Numpy para velocidad máxima y compatibilidad.
    """
    balance = 1000.0
    posicion = False
    precio_compra = 0.0
    max_visto = 0.0
    ops = 0
    wins = 0
    leverage = 1.2
    
    equity = np.zeros(len(closes))
    equity[0] = balance
    
    # Pre-calcular señales de compra
    signals = (ema_fast > ema_slow) & (adx > p['adx_u']) & (bbw < p['bbw_u']) & (rsi < 80)
    
    for i in range(1, len(closes)):
        if not posicion:
            if signals[i]:
                posicion = True
                precio_compra = closes[i]
                max_visto = highs[i]
                balance -= balance * 0.001
        else:
            max_visto = max(max_visto, highs[i])
            perdida = (precio_compra - lows[i]) / (precio_compra + 1e-10)
            caida_max = (max_visto - lows[i]) / (max_visto + 1e-10)
            
            if perdida > p['sl'] or caida_max > p['ts'] or ema_fast[i] < ema_slow[i]:
                pnl = (closes[i] - precio_compra) / (precio_compra + 1e-10) * leverage
                balance *= (1 + pnl)
                balance -= balance * 0.001
                posicion = False
                ops += 1
                if pnl > 0: wins += 1
                
        equity[i] = balance
        if balance <= 10: # Liquidación total
            equity[i:] = 0
            break

    profit = ((balance - 1000) / 1000) * 100
    
    # Max Drawdown
    max_eq = np.maximum.accumulate(equity)
    dd = (equity - max_eq) / (max_eq + 1e-10)
    max_dd = np.min(dd) * 100
    
    return {
        'profit': profit,
        'max_dd': max_dd,
        'ops': ops,
        'score': profit / abs(max_dd) if max_dd < -1 else profit / 100
    }

def ejecutar_optimizacion():
    print("--- 🚀 INICIANDO SUPER-OPTIMIZADOR HYDRA (NUMPY EDITION) ---")
    
    df = pd.read_parquet("datos/btc_usdt_1h.parquet")
    
    # Indicadores Base que NO dependen de los parámetros variables del loop principal
    df['sma_20'] = df['close'].rolling(20).mean()
    df['std_20'] = df['close'].rolling(20).std()
    df['bb_width'] = (df['std_20'] * 4) / (df['sma_20'] + 1e-10)
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    plus_dm = df['high'].diff().clip(lower=0)
    minus_dm = -df['low'].diff().clip(upper=0)
    tr = pd.concat([df['high']-df['low'], abs(df['high']-df['close'].shift(1)), abs(df['low']-df['close'].shift(1))], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    plus_di = 100 * (plus_dm.rolling(14).mean() / (atr + 1e-10))
    minus_di = 100 * (minus_dm.rolling(14).mean() / (atr + 1e-10))
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    df['adx'] = dx.rolling(14).mean()
    
    df = df.dropna()
    
    # Arrays Numpy para el motor
    data = {
        'closes': df['close'].values,
        'lows': df['low'].values,
        'highs': df['high'].values,
        'adx': df['adx'].values,
        'bbw': df['bb_width'].values,
        'rsi': df['rsi'].values
    }

    # Espacio de búsqueda
    grid = {
        'fast': [20, 35, 50, 65],
        'slow': [100, 150, 200, 300],
        'adx_u': [20, 25, 30],
        'bbw_u': [0.10, 0.12, 0.15],
        'sl': [0.05, 0.07, 0.09],
        'ts': [0.10, 0.15]
    }
    
    keys, values = zip(*grid.items())
    permutaciones = [dict(zip(keys, v)) for v in product(*values)]
    
    # Pre-calcular todas las EMAs posibles para no repetirlas
    print("Pre-calculando EMAs...")
    emas_fast = {f: df['close'].ewm(span=f, adjust=False).mean().values for f in grid['fast']}
    emas_slow = {s: df['close'].ewm(span=s, adjust=False).mean().values for s in grid['slow']}
    
    print(f"Combinaciones a procesar: {len(permutaciones)}")
    
    def worker(p):
        res = simulacion_core(
            data['closes'], data['lows'], data['highs'], 
            data['adx'], data['bbw'], data['rsi'],
            emas_fast[p['fast']], emas_slow[p['slow']], p
        )
        res['params'] = p
        return res

    # Ejecución paralela
    resultados = Parallel(n_jobs=-1, verbose=1)(delayed(worker)(p) for p in permutaciones)
    
    # Top 15 por Score
    top = sorted(resultados, key=lambda x: x['score'], reverse=True)[:15]
    
    print("\n" + "="*80)
    print(f"{'RANK':<5} | {'PROFIT':<10} | {'MAX DD':<10} | {'OPS':<5} | {'PARAMS'}")
    print("="*80)
    
    for i, r in enumerate(top):
        p = r['params']
        p_str = f"F:{p['fast']} S:{p['slow']} ADX:{p['adx_u']} BBW:{p['bbw_u']} SL:{p['sl']} TS:{p['ts']}"
        print(f"#{i+1:<4} | {r['profit']:>8.1f}% | {r['max_dd']:>8.2f}% | {r['ops']:<5} | {p_str}")

if __name__ == "__main__":
    start = time.time()
    ejecutar_optimizacion()
    print(f"\n✅ Terminado en {time.time() - start:.2f}s")
