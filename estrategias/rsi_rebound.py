import pandas as pd
import numpy as np
from estrategias.base import EstrategiaBase

class EstrategiaRSI(EstrategiaBase):
    def __init__(self):
        super().__init__(nombre="Francotirador RSI (30/70)")
        self.periodo_rsi = 14
        self.sobreventa = 30  # Comprar aquí
        self.sobrecompra = 70 # Vender aquí

    def generar_indicadores(self, df):
        # Cálculo manual de RSI vectorizado (Ultra rápido y sin librerías pesadas)
        delta = df['close'].diff()
        
        # Separamos ganancias y pérdidas
        gain = (delta.where(delta > 0, 0)).fillna(0)
        loss = (-delta.where(delta < 0, 0)).fillna(0)

        # Media Móvil Exponencial (Wilder's Smoothing)
        avg_gain = gain.ewm(com=self.periodo_rsi - 1, min_periods=self.periodo_rsi).mean()
        avg_loss = loss.ewm(com=self.periodo_rsi - 1, min_periods=self.periodo_rsi).mean()

        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        return df

    def proximo_paso(self, vela):
        # Si no hay dato de RSI (los primeros 14 días), esperamos
        if pd.isna(vela['rsi']):
            return 'ESPERAR'

        # 1. COMPRA: Si el RSI cae por debajo de 30 (Pánico en el mercado)
        if vela['rsi'] < self.sobreventa and self.posicion is None:
            return 'COMPRAR'
        
        # 2. VENTA: Si el RSI sube por encima de 70 (Euforia en el mercado)
        elif vela['rsi'] > self.sobrecompra and self.posicion == 'COMPRADO':
            return 'VENDER'
        
        return 'ESPERAR'
