import pandas as pd
import numpy as np

class EstrategiaSuperHidra:
    def __init__(self, inversion_inicial=1000.0):
        self.posicion = None 
        self.precio_compra = 0.0
        self.balance_actual = inversion_inicial
        self.historial_operaciones = []
        self.periodo_rapido = 50
        self.periodo_lento = 200
        self.umbral_adx = 25

    def generar_indicadores(self, df):
        df['ema_50'] = df['close'].ewm(span=self.periodo_rapido, adjust=False).mean()
        df['ema_200'] = df['close'].ewm(span=self.periodo_lento, adjust=False).mean()
        df['volumen_ma'] = df['volume'].rolling(window=20).mean()
        df['tr'] = np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))
        df['up'] = df['high'] - df['high'].shift(1)
        df['down'] = df['low'].shift(1) - df['low']
        df['pdm'] = np.where((df['up'] > df['down']) & (df['up'] > 0), df['up'], 0)
        df['mdm'] = np.where((df['down'] > df['up']) & (df['down'] > 0), df['down'], 0)
        tr_s = df['tr'].ewm(alpha=1/14, adjust=False).mean()
        pdm_s = df['pdm'].ewm(alpha=1/14, adjust=False).mean()
        mdm_s = df['mdm'].ewm(alpha=1/14, adjust=False).mean()
        dx = 100 * abs((pdm_s/tr_s) - (mdm_s/tr_s)) / ((pdm_s/tr_s) + (mdm_s/tr_s))
        df['adx'] = dx.ewm(alpha=1/14, adjust=False).mean()
        return df

    def proximo_paso(self, vela):
        if pd.isna(vela['adx']) or pd.isna(vela['ema_200']): return 'ESPERAR'
        tendencia_alcista = vela['ema_50'] > vela['ema_200']
        if self.posicion == 'COMPRADO' and not tendencia_alcista: return 'VENDER'
        elif self.posicion is None and tendencia_alcista and vela['adx'] > self.umbral_adx and vela['volume'] > vela['volumen_ma']: return 'COMPRAR'
        return 'ESPERAR'

    def ejecutar_orden(self, tipo, precio, fecha):
        comision = 0.001
        if tipo == 'COMPRAR':
            self.posicion = 'COMPRADO'
            self.precio_compra = precio
            self.balance_actual -= self.balance_actual * comision
        elif tipo == 'VENDER':
            self.posicion = None
            resultado = (precio - self.precio_compra) / self.precio_compra
            self.balance_actual = self.balance_actual * (1 + resultado)
            self.balance_actual -= self.balance_actual * comision

def ejecutar_macro():
    df = pd.read_parquet('datos/btc_usd_1d_macro.parquet')
    bot = EstrategiaSuperHidra()
    df = bot.generar_indicadores(df)
    equity = []
    for _, row in df.iterrows():
        dec = bot.proximo_paso(row)
        if dec == 'COMPRAR': bot.ejecutar_orden('COMPRAR', row['close'], 0)
        elif dec == 'VENDER': bot.ejecutar_orden('VENDER', row['close'], 0)
        equity.append(bot.balance_actual)

    print(f"\n🌍 --- PRUEBA MAESTRA (MACRO 2014-2026) ---")
    print(f"💰 Balance Inicial: $1000.00")
    print(f"💰 Balance Final:   ${bot.balance_actual:.2f}")
    print(f"📈 Retorno Total:   {((bot.balance_actual-1000)/10):.2f}%")
    mdd = ((pd.Series(equity) - pd.Series(equity).cummax()) / pd.Series(equity).cummax()).min() * 100
    print(f"📉 Max Drawdown:    {mdd:.2f}%")

if __name__ == "__main__": ejecutar_macro()
