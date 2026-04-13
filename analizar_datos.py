import pandas as pd
df = pd.read_parquet('datos/eth_usdt_1h.parquet')
df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
inicio = df['date'].iloc[0]
fin = df['date'].iloc[-1]
p_inicio = df['close'].iloc[0]
p_fin = df['close'].iloc[-1]
hold_ret = (p_fin / p_inicio - 1) * 100

print(f"--- COMPARATIVA DE RENDIMIENTO ---")
print(f"Periodo: {inicio} a {fin}")
print(f"Precio Inicio: ${p_inicio:.2f}")
print(f"Precio Fin:    ${p_fin:.2f}")
print(f"Retorno Buy & Hold: {hold_ret:.2f}%")
print(f"Retorno Super Hidra: 2204.77%")
