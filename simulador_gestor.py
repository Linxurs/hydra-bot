import pandas as pd
import numpy as np

# Importamos a los Soldados
from estrategias.super_hidra import EstrategiaSuperHidra 
from estrategias.rsi_rebound import EstrategiaRSI
from estrategias.cruce_simple import EstrategiaCruce

class GestorDeEstrategias:
    def __init__(self):
        # 1. Inicializamos el Escuadrón
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
        # --- CÁLCULO DE ATR (Volatilidad) ---
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = abs(df['high'] - df['close'].shift(1))
        df['tr3'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        df['atr_macro'] = df['tr'].ewm(alpha=1/self.atr_periodo, min_periods=self.atr_periodo).mean()
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

        sum_di = df['plus_di'] + df['minus_di']
        sum_di = sum_di.replace(0, 1)
        dx = 100 * abs(df['plus_di'] - df['minus_di']) / sum_di
        df['adx_macro'] = dx.ewm(alpha=1/self.adx_periodo, min_periods=self.adx_periodo).mean()

        return df

    def preparar_estrategias(self, df):
        print("   ⚙️ Gestor: Afilando las armas de la Super Hidra y el RSI...")
        df = self.soldado_tendencia.generar_indicadores(df)
        df = self.soldado_rango.generar_indicadores(df)
        return df

    def decidir(self, vela):
        if pd.isna(vela.get('adx_macro')) or pd.isna(vela.get('volatilidad_pct')):
            return "ESPERAR", "Cargando..."

        # REGLA DE ORO: Mantener al capitán si tiene posición abierta
        if self.soldado_tendencia.posicion == 'COMPRADO':
            return self.soldado_tendencia.proximo_paso(vela), "Mando: Super Hidra (Abierto)"
        
        if self.soldado_rango.posicion == 'COMPRADO':
            return self.soldado_rango.proximo_paso(vela), "Mando: RSI (Abierto)"

        adx = vela['adx_macro']
        volatilidad = vela['volatilidad_pct']

        # ESCENARIO A: TENDENCIA (Super Hidra)
        if adx > 23: 
            self.regimen_actual = "TENDENCIA"
            decision = self.soldado_tendencia.proximo_paso(vela)
            return decision, "Mando: Super Hidra"

        # ESCENARIO B: RANGO (RSI)
        elif adx < 20 and volatilidad < 1.5:
            self.regimen_actual = "RANGO"
            decision = self.soldado_rango.proximo_paso(vela)
            return decision, "Mando: RSI"

        else:
            self.regimen_actual = "RUIDO"
            return "ESPERAR", "Mercado Sucio"

    def ejecutar_accion_real(self, decision, precio, fecha):
        # === AQUÍ ESTABA EL ERROR ===
        # Antes buscábamos "Super Hidra" o "TVB", pero la variable self.regimen_actual dice "TENDENCIA".
        # Ahora coincidimos las palabras clave.
        
        # Caso 1: Estamos en régimen de TENDENCIA o la Super Hidra ya tiene la posición comprada
        if self.regimen_actual == "TENDENCIA" or self.soldado_tendencia.posicion == 'COMPRADO':
            self.soldado_tendencia.ejecutar_orden(decision, precio, fecha)
            return self.soldado_tendencia.balance_actual
            
        # Caso 2: Estamos en régimen de RANGO o el RSI ya tiene la posición comprada
        elif self.regimen_actual == "RANGO" or self.soldado_rango.posicion == 'COMPRADO':
            self.soldado_rango.ejecutar_orden(decision, precio, fecha)
            return self.soldado_rango.balance_actual
            
        return 1000.0
