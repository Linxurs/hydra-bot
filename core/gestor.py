import pandas as pd
import numpy as np

# Importamos a los Soldados (Ahora con la Super Hidra)
from estrategias.super_hidra import EstrategiaSuperHidra # <-- El nuevo Capitán
from estrategias.rsi_rebound import EstrategiaRSI
from estrategias.cruce_simple import EstrategiaCruce

class GestorDeEstrategias:
    def __init__(self):
        # 1. Inicializamos el Escuadrón
        # REEMPLAZO: Usamos Super Hidra en lugar de TVB para la tendencia
        self.soldado_tendencia = EstrategiaSuperHidra() 
        self.soldado_rango = EstrategiaRSI()
        self.soldado_reserva = EstrategiaCruce()
        
        # 2. Estado del Gestor
        self.estrategia_activa = None
        self.regimen_actual = "NEUTRO"
        
        # Configuración del Juez
        self.adx_periodo = 14
        self.atr_periodo = 14

    def calcular_indicadores_macro(self, df):
        """
        El Gestor calcula sus propios indicadores para decidir quién manda.
        """
        # --- CÁLCULO DE ATR (Volatilidad) ---
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = abs(df['high'] - df['close'].shift(1))
        df['tr3'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        df['atr_macro'] = df['tr'].ewm(alpha=1/self.atr_periodo, min_periods=self.atr_periodo).mean()
        
        # Porcentaje de volatilidad
        df['volatilidad_pct'] = (df['atr_macro'] / df['close']) * 100

        # --- CÁLCULO DE ADX (Fuerza) ---
        df['up_move'] = df['high'] - df['high'].shift(1)
        df['down_move'] = df['low'].shift(1) - df['low']
        
        df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
        df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)

        tr_smooth = df['tr'].ewm(alpha=1/self.adx_periodo, min_periods=self.adx_periodo).mean()
        plus_dm_smooth = df['plus_dm'].ewm(alpha=1/self.adx_periodo, min_periods=self.adx_periodo).mean()
        minus_dm_smooth = df['minus_dm'].ewm(alpha=1/self.adx_periodo, min_periods=self.adx_periodo).mean()

        df['plus_di'] = 100 * (plus_dm_smooth / tr_smooth)
        df['minus_di'] = 100 * (minus_dm_smooth / tr_smooth)

        # Evitar división por cero
        sum_di = df['plus_di'] + df['minus_di']
        sum_di = sum_di.replace(0, 1) # Parche de seguridad
        
        dx = 100 * abs(df['plus_di'] - df['minus_di']) / sum_di
        df['adx_macro'] = dx.ewm(alpha=1/self.adx_periodo, min_periods=self.adx_periodo).mean()

        return df

    def preparar_estrategias(self, df):
        """
        Prepara a los soldados (calculan sus propios indicadores en el mapa común)
        """
        print("   ⚙️ Gestor: Afilando las armas de la Super Hidra y el RSI...")
        
        # 1. Super Hidra calcula sus cosas (SMA, Filtro 4H, etc.)
        df = self.soldado_tendencia.generar_indicadores(df)
        
        # 2. RSI calcula sus cosas
        df = self.soldado_rango.generar_indicadores(df)
        
        return df

    def decidir(self, vela):
        # 1. Seguridad de datos
        if pd.isna(vela.get('adx_macro')) or pd.isna(vela.get('volatilidad_pct')):
            return "ESPERAR", "Cargando..."

        # 2. REGLA DE ORO: Mantener al capitán si tiene posición abierta
        if self.soldado_tendencia.posicion == 'COMPRADO':
            return self.soldado_tendencia.proximo_paso(vela), "Mando: Super Hidra (Abierto)"
        
        if self.soldado_rango.posicion == 'COMPRADO':
            return self.soldado_rango.proximo_paso(vela), "Mando: RSI (Abierto)"

        # 3. ELECCIÓN DEL RÉGIMEN
        adx = vela['adx_macro']
        volatilidad = vela['volatilidad_pct']

        # ESCENARIO A: TENDENCIA (Usamos Super Hidra)
        # Bajamos un poco el umbral a 23 para ser más agresivos entrando a la tendencia
        if adx > 23: 
            self.regimen_actual = "TENDENCIA"
            decision = self.soldado_tendencia.proximo_paso(vela)
            return decision, "Mando: Super Hidra"

        # ESCENARIO B: RANGO (Usamos RSI)
        elif adx < 20 and volatilidad < 1.5:
            self.regimen_actual = "RANGO"
            decision = self.soldado_rango.proximo_paso(vela)
            return decision, "Mando: RSI"

        # ESCENARIO C: RUIDO
        else:
            self.regimen_actual = "RUIDO"
            # Opcional: Podríamos dejar que Super Hidra intente operar aquí también
            # ya que tiene su propio filtro interno, pero por seguridad, esperamos.
            return "ESPERAR", "Mercado Sucio"

    def ejecutar_accion_real(self, decision, precio, fecha):
        # Actualizamos la billetera del soldado correspondiente
        if "Super Hidra" in self.regimen_actual or "TVB" in self.regimen_actual or self.soldado_tendencia.posicion == 'COMPRADO':
            self.soldado_tendencia.ejecutar_orden(decision, precio, fecha)
            return self.soldado_tendencia.balance_actual
            
        elif "RSI" in self.regimen_actual or self.soldado_rango.posicion == 'COMPRADO':
            self.soldado_rango.ejecutar_orden(decision, precio, fecha)
            return self.soldado_rango.balance_actual
            
        return 1000.0
