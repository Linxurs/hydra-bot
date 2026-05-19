import pandas as pd
import numpy as np
from estrategias.base import EstrategiaBase

class EstrategiaEHMT(EstrategiaBase):
    def __init__(self):
        super().__init__(nombre="EHMT Clásica (Medias+RSI+Vol)")
        self.stop_loss_price = 0.0

    def generar_indicadores(self, df):
        # Medias Exponenciales
        df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean() # Filtro diario aprox (usamos 200 en 1h como proxy rápido)

        # RSI 14
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).fillna(0)
        loss = (-delta.where(delta < 0, 0)).fillna(0)
        avg_gain = gain.ewm(com=13, min_periods=14).mean()
        avg_loss = loss.ewm(com=13, min_periods=14).mean()
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # Volumen Promedio (20 velas)
        df['vol_avg'] = df['volume'].rolling(window=20).mean()

        # ATR para Stop Loss
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = abs(df['high'] - df['close'].shift(1))
        df['tr3'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        df['atr'] = df['tr'].ewm(span=14, adjust=False).mean()

        return df

    def proximo_paso(self, vela):
        if pd.isna(vela['ema_200']) or pd.isna(vela['rsi']):
            return 'ESPERAR'

        # --- SALIDAS ---
        if self.posicion == 'COMPRADO':
            # Stop Loss (Fijo al inicio del trade)
            if vela['low'] < self.stop_loss_price:
                return 'VENDER'
            
            # Take Profit Técnico: RSI sobrecomprado extremo
            if vela['rsi'] > 80:
                return 'VENDER'
            
            # Salida por cambio de tendencia (Cruce bajista)
            if vela['ema_9'] < vela['ema_21']:
                return 'VENDER'

        # --- ENTRADAS ---
        if self.posicion is None:
            # 1. Filtro de Tendencia General (Precio > EMA 200)
            if vela['close'] < vela['ema_200']:
                return 'ESPERAR'

            # 2. Señal de Cruce (EMA 9 > EMA 21)
            cruce_alcista = vela['ema_9'] > vela['ema_21']
            
            # 3. Filtro de Momentum (RSI entre 45 y 70)
            rsi_ok = 45 < vela['rsi'] < 70
            
            # 4. Filtro de Volumen (Volumen actual > Promedio)
            volumen_ok = vela['volume'] > vela['vol_avg']

            if cruce_alcista and rsi_ok and volumen_ok:
                # Fijamos Stop Loss inicial: Precio - 2 ATR
                self.stop_loss_price = vela['close'] - (2 * vela['atr'])
                return 'COMPRAR'

        return 'ESPERAR'
