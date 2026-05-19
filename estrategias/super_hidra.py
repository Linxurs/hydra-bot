import pandas as pd
import numpy as np
from estrategias.base import EstrategiaBase

class EstrategiaSuperHidra(EstrategiaBase):
    def __init__(self):
        super().__init__(nombre="SUPER HIDRA (ADX + Filtro 4H)")
        # --- PARÁMETROS ---
        # 1. Tendencia (Cruce)
        self.sma_rapida = 50
        self.sma_lenta = 200
        # 2. Rango (RSI)
        self.rsi_periodo = 14
        self.rsi_compra = 30
        self.rsi_venta = 70
        # 3. El Juez (ADX)
        self.adx_periodo = 14
        self.umbral_adx = 25
        # 4. Seguridad (Filtro Macro)
        self.usar_filtro_macro = True

        # 5. Control de Riesgo (Mejora Drawdown)
        self.stop_loss_pct = 0.10  # 10%
        self.trailing_stop_pct = 0.15  # 15%
        self.max_precio_visto = 0.0

    def generar_indicadores(self, df):
        # ==========================================
        # 1. INDICADORES BÁSICOS (SMA + RSI)
        # ==========================================
        df['sma_50'] = df['close'].rolling(window=self.sma_rapida).mean()
        df['sma_200'] = df['close'].rolling(window=self.sma_lenta).mean()

        # Cálculo RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).fillna(0)
        loss = (-delta.where(delta < 0, 0)).fillna(0)
        avg_gain = gain.ewm(com=self.rsi_periodo - 1, min_periods=self.rsi_periodo).mean()
        avg_loss = loss.ewm(com=self.rsi_periodo - 1, min_periods=self.rsi_periodo).mean()
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # ==========================================
        # 2. CÁLCULO COMPLETO DEL ADX (El Juez)
        # ==========================================
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

        # Suavizado (Wilder's Smoothing)
        # Usamos alpha=1/periodo para emular el suavizado de Wilder
        tr_smooth = df['tr'].ewm(alpha=1/self.adx_periodo, min_periods=self.adx_periodo).mean()
        plus_dm_smooth = df['plus_dm'].ewm(alpha=1/self.adx_periodo, min_periods=self.adx_periodo).mean()
        minus_dm_smooth = df['minus_dm'].ewm(alpha=1/self.adx_periodo, min_periods=self.adx_periodo).mean()

        # DI+ y DI-
        # Evitamos división por cero sumando un epsilon minúsculo si hace falta, o Pandas maneja nans
        df['plus_di'] = 100 * (plus_dm_smooth / tr_smooth)
        df['minus_di'] = 100 * (minus_dm_smooth / tr_smooth)

        # ADX Final
        dx = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])
        df['adx'] = dx.ewm(alpha=1/self.adx_periodo, min_periods=self.adx_periodo).mean()

        # ==========================================
        # 3. EL FILTRO MACRO (Tendencia 4 Horas)
        # ==========================================
        # Hacemos una copia y seteamos el índice como fecha para poder hacer "Resample"
        df_temp = df.set_index('date').copy()
        
        # Agrupamos las velas de 1h en bloques de 4h y tomamos el último precio de cierre
        df_4h = df_temp['close'].resample('4h').last()
        
        # Calculamos la EMA 200 sobre esas velas de 4h
        ema_200_4h = df_4h.ewm(span=200, adjust=False).mean()
        
        # IMPORTANTE: Desplazamos 1 periodo para evitar "Look-Ahead Bias"
        # Esto asegura que en la hora T solo conocemos la media del bloque de 4h anterior.
        ema_200_4h_shifted = ema_200_4h.shift(1)
        
        # Devolvemos esa línea al gráfico de 1h (rellenando los huecos hacia adelante)
        df_temp['ema_macro'] = ema_200_4h_shifted.reindex(df_temp.index, method='ffill')
        
        # Pasamos la columna calculada al DataFrame original
        df['ema_macro'] = df_temp['ema_macro'].values

        return df

    def proximo_paso(self, vela):
        # 1. Seguridad: Si faltan datos críticos, esperamos
        if pd.isna(vela['adx']) or pd.isna(vela['sma_200']) or pd.isna(vela['ema_macro']):
            return 'ESPERAR'

        # 1.1 Salida de Emergencia (Mejora Drawdown)
        if self.posicion == 'COMPRADO':
            # Actualización de Máximo
            self.max_precio_visto = max(self.max_precio_visto, vela['close'])
            
            # Cálculo de Caída desde Máximo
            caida_desde_max = (self.max_precio_visto - vela['close']) / self.max_precio_visto
            
            # Cálculo de Pérdida desde Compra
            perdida_actual = (self.precio_compra - vela['close']) / self.precio_compra
            
            # Decisión de Salida
            if perdida_actual > self.stop_loss_pct:
                return 'VENDER_STOP_LOSS'
            
            if caida_desde_max > self.trailing_stop_pct:
                return 'VENDER_TRAILING_STOP'
        else:
            # Si no estamos en posición, reseteamos el máximo visto
            self.max_precio_visto = 0.0

        # 2. Análisis del Entorno
        es_tendencia_fuerte = vela['adx'] > self.umbral_adx
        # La tendencia macro es alcista si el precio está por encima de la media de 4H
        tendencia_macro_alcista = vela['close'] > vela['ema_macro']

        # === CEREBRO DE LA SUPER HIDRA ===
        
        if es_tendencia_fuerte:
            # MODO: TENDENCIA (Usamos Cruce de Medias)
            # Aquí no nos importa el filtro macro tanto, porque el ADX dice que hay fuerza AHORA.
            if vela['sma_50'] > vela['sma_200'] and self.posicion is None:
                return 'COMPRAR'
            elif vela['sma_50'] < vela['sma_200'] and self.posicion == 'COMPRADO':
                return 'VENDER'

        else:
            # MODO: RANGO/LATERAL (Usamos RSI)
            # AQUI es donde activamos la seguridad extra.
            
            # REGLA: Solo compramos rebotes (RSI < 30) si la tendencia mayor (4H) es Alcista.
            # Si el mercado general (4H) se está cayendo a pedazos, NO compramos el rebote.
            if self.usar_filtro_macro and not tendencia_macro_alcista:
                # Estamos en rango en 1H, pero en caída libre en 4H -> PELIGRO
                if self.posicion == 'COMPRADO' and vela['rsi'] > self.rsi_venta:
                    return 'VENDER' # Si ya estábamos dentro, permitimos salir
                return 'ESPERAR' 

            # Si pasamos el filtro (o está desactivado), operamos RSI normal
            if vela['rsi'] < self.rsi_compra and self.posicion is None:
                return 'COMPRAR'
            elif vela['rsi'] > self.rsi_venta and self.posicion == 'COMPRADO':
                return 'VENDER'
        
        return 'ESPERAR'
