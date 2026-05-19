import pandas as pd
import numpy as np
from estrategias.base import EstrategiaBase

class EstrategiaHidra(EstrategiaBase):
    def __init__(self):
        super().__init__(nombre="HIDRA v1 (ADX Selector)")
        # Parámetros Medias
        self.sma_rapida = 50
        self.sma_lenta = 200
        # Parámetros RSI
        self.rsi_periodo = 14
        self.rsi_compra = 30
        self.rsi_venta = 70
        # Parámetros ADX (El Juez)
        self.adx_periodo = 14
        self.umbral_adx = 25  # Por encima de esto, usamos Tendencia

    def generar_indicadores(self, df):
        # --- 1. Calcular Medias (SMA) ---
        df['sma_50'] = df['close'].rolling(window=self.sma_rapida).mean()
        df['sma_200'] = df['close'].rolling(window=self.sma_lenta).mean()

        # --- 2. Calcular RSI ---
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).fillna(0)
        loss = (-delta.where(delta < 0, 0)).fillna(0)
        avg_gain = gain.ewm(com=self.rsi_periodo - 1, min_periods=self.rsi_periodo).mean()
        avg_loss = loss.ewm(com=self.rsi_periodo - 1, min_periods=self.rsi_periodo).mean()
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # --- 3. Calcular ADX (Matemáticas Avanzadas) ---
        # True Range
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = abs(df['high'] - df['close'].shift(1))
        df['tr3'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)

        # Directional Movement
        df['up_move'] = df['high'] - df['high'].shift(1)
        df['down_move'] = df['low'].shift(1) - df['low']
        
        df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
        df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)

        # Suavizado (Wilder)
        tr_smooth = df['tr'].ewm(alpha=1/self.adx_periodo, min_periods=self.adx_periodo).mean()
        plus_dm_smooth = pd.Series(df['plus_dm']).ewm(alpha=1/self.adx_periodo, min_periods=self.adx_periodo).mean()
        minus_dm_smooth = pd.Series(df['minus_dm']).ewm(alpha=1/self.adx_periodo, min_periods=self.adx_periodo).mean()

        # DI+ y DI-
        df['plus_di'] = 100 * (plus_dm_smooth / tr_smooth)
        df['minus_di'] = 100 * (minus_dm_smooth / tr_smooth)

        # ADX Final
        dx = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])
        df['adx'] = dx.ewm(alpha=1/self.adx_periodo, min_periods=self.adx_periodo).mean()

        return df

    def proximo_paso(self, vela):
        # Si faltan datos, esperar
        if pd.isna(vela['adx']) or pd.isna(vela['sma_200']):
            return 'ESPERAR'

        # === EL CEREBRO ===
        es_tendencia_fuerte = vela['adx'] > self.umbral_adx

        if es_tendencia_fuerte:
            # MODO: TENDENCIA (Usamos SMA)
            # Solo compramos si la tendencia es alcista clara
            if vela['sma_50'] > vela['sma_200'] and self.posicion is None:
                return 'COMPRAR'
            elif vela['sma_50'] < vela['sma_200'] and self.posicion == 'COMPRADO':
                return 'VENDER'

        else:
            # MODO: RANGO/LATERAL (Usamos RSI)
            # Compramos rebotes
            if vela['rsi'] < self.rsi_compra and self.posicion is None:
                return 'COMPRAR'
            elif vela['rsi'] > self.rsi_venta and self.posicion == 'COMPRADO':
                return 'VENDER'
        
        return 'ESPERAR'
