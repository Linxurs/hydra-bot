import pandas as pd
import numpy as np
from estrategias.base import EstrategiaBase

class EstrategiaTVB(EstrategiaBase):
    def __init__(self):
        super().__init__(nombre="TVB Institucional (Trend+Vol)")
        # Parámetros
        self.risk_per_trade = 0.02 # 2% riesgo por trade (Simplificado para simulación)
        self.atr_periodo = 14
        self.bb_periodo = 20
        self.bb_std = 2.0
        self.trailing_sl = 0.0

    def generar_indicadores(self, df):
        # 1. INDICADORES 1H (Operativos)
        # EMA 50
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        
        # ATR (Volatilidad)
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = abs(df['high'] - df['close'].shift(1))
        df['tr3'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        df['atr'] = df['tr'].ewm(span=self.atr_periodo, adjust=False).mean()
        
        # Filtro de Expansión de Volatilidad (ATR > Media de ATR)
        df['atr_sma'] = df['atr'].rolling(window=50).mean() # Usamos media de 50 periodos
        
        # Bandas de Bollinger (Para el Breakout)
        df['bb_mid'] = df['close'].rolling(window=self.bb_periodo).mean()
        df['bb_std'] = df['close'].rolling(window=self.bb_periodo).std()
        df['bb_upper'] = df['bb_mid'] + (df['bb_std'] * self.bb_std)
        df['bb_lower'] = df['bb_mid'] - (df['bb_std'] * self.bb_std)

        # 2. INDICADORES 4H (Filtro Macro - El Truco)
        # Resampleamos a 4 horas para calcular la EMA200 Macro
        # set_index temporalmente para poder hacer resample por tiempo
        df_temp = df.set_index('date')
        df_4h = df_temp['close'].resample('4h').last() # Tomamos el cierre de cada 4h
        ema_200_4h = df_4h.ewm(span=200, adjust=False).mean()
        
        # Devolvemos la EMA 4h al timeframe de 1h (rellenando huecos)
        df_temp['ema_200_macro'] = ema_200_4h.reindex(df_temp.index, method='ffill')
        
        # Recuperamos el dataframe original con la nueva columna
        df['ema_200_macro'] = df_temp['ema_200_macro'].values
        
        return df

    def proximo_paso(self, vela):
        # Si faltan datos, esperar
        if pd.isna(vela['ema_200_macro']) or pd.isna(vela['atr_sma']):
            return 'ESPERAR'

        # --- GESTIÓN DE SALIDA (Trailing Stop Manual) ---
        if self.posicion == 'COMPRADO':
            # Stop Loss Dinámico: Precio - 2.2 ATR
            stop_dinamico = vela['close'] - (2.2 * vela['atr'])
            
            # Solo subimos el stop, nunca lo bajamos
            if stop_dinamico > self.trailing_sl:
                self.trailing_sl = stop_dinamico
            
            # Si el precio toca nuestro trailing stop -> VENDER
            if vela['low'] < self.trailing_sl:
                return 'VENDER'
                
            # Salida por reversión (Cruce de EMA50)
            if vela['close'] < vela['ema_50']:
                return 'VENDER'

        # --- LÓGICA DE ENTRADA (SOLO LONG) ---
        if self.posicion is None:
            # 1. Filtro de Tendencia Macro (4H)
            es_alcista_macro = vela['close'] > vela['ema_200_macro']
            
            if not es_alcista_macro:
                return 'ESPERAR'

            # 2. Condiciones de Entrada (1H)
            # - Precio encima de EMA 50
            # - Expansión de volatilidad (ATR actual > Promedio ATR)
            # - Breakout (Precio rompe banda superior Bollinger)
            condicion_1 = vela['close'] > vela['ema_50']
            condicion_2 = vela['atr'] > vela['atr_sma']
            condicion_3 = vela['close'] > vela['bb_upper']

            if condicion_1 and condicion_2 and condicion_3:
                # Definimos el Trailing Stop inicial
                self.trailing_sl = vela['close'] - (1.6 * vela['atr'])
                return 'COMPRAR'

        return 'ESPERAR'
