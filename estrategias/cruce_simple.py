import pandas as pd
from estrategias.base import EstrategiaBase

class EstrategiaCruce(EstrategiaBase):
    def __init__(self):
        # Llamamos al constructor del padre
        super().__init__(nombre="Cruce de Oro (SMA 50/200)")
        self.sma_rapida = 50
        self.sma_lenta = 200

    def generar_indicadores(self, df):
        # Calculamos las medias móviles usando Pandas (Vectorizado = Rápido)
        # .rolling() crea una ventana deslizante
        df['sma_50'] = df['close'].rolling(window=self.sma_rapida).mean()
        df['sma_200'] = df['close'].rolling(window=self.sma_lenta).mean()
        return df

    def proximo_paso(self, vela):
        # vela es una fila del DataFrame con los datos de ESA hora
        
        # Si no tenemos datos suficientes para calcular la media de 200, esperamos
        if pd.isna(vela['sma_200']):
            return 'ESPERAR'

        # Lógica de COMPRA
        if vela['sma_50'] > vela['sma_200'] and self.posicion is None:
            return 'COMPRAR'
        
        # Lógica de VENTA
        elif vela['sma_50'] < vela['sma_200'] and self.posicion == 'COMPRADO':
            return 'VENDER'
        
        return 'ESPERAR'
