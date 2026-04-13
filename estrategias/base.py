import pandas as pd

class EstrategiaBase:
    def __init__(self, nombre="Estrategia Generica"):
        self.nombre = nombre
        self.posicion = None  # None = No tenemos nada. 'COMPRADO' = Tenemos BTC.
        self.precio_compra = 0.0
        self.balance_inicial = 1000.0  # Dólares ficticios
        self.balance_actual = 1000.0
        self.historial_operaciones = []

    def generar_indicadores(self, df):
        """
        Aquí es donde cada estrategia hija hará sus cálculos matemáticos.
        Por defecto, esta base no hace nada.
        """
        return df

    def proximo_paso(self, vela_actual):
        """
        Esta función se ejecutará CADA HORA (o cada vela).
        Debe devolver: 'COMPRAR', 'VENDER' o 'ESPERAR'.
        """
        return 'ESPERAR'

    def ejecutar_orden(self, tipo, precio, fecha):
        """
        Simula la ejecución de una orden y actualiza el balance.
        """
        comision = 0.001 # 0.1% por operación (Binance estándar)
        
        if tipo == 'COMPRAR' and self.posicion is None:
            self.posicion = 'COMPRADO'
            self.precio_compra = precio
            # Simulamos que gastamos todo el balance en comprar BTC
            cantidad_btc = self.balance_actual / precio
            self.historial_operaciones.append({
                'fecha': fecha,
                'tipo': 'COMPRA',
                'precio': precio,
                'balance': self.balance_actual
            })
            print(f"[{self.nombre}] 🟢 COMPRA en {precio:.2f} el {fecha}")
            costo_fee = self.balance_actual * comision
            self.balance_actual -= costo_fee # <-- Nos cobramos la entrada

        elif tipo == 'VENDER' and self.posicion == 'COMPRADO':
            self.posicion = None
            # Calculamos ganancia/pérdida
            # Fórmula: (Precio Venta - Precio Compra) / Precio Compra * 100
            resultado = (precio - self.precio_compra) / self.precio_compra
            self.balance_actual = self.balance_actual * (1 + resultado)
            
            self.historial_operaciones.append({
                'fecha': fecha,
                'tipo': 'VENTA',
                'precio': precio,
                'balance': self.balance_actual,
                'resultado_pct': resultado * 100
            })
            emoji = "💰" if resultado > 0 else "🔻"
            print(f"[{self.nombre}] 🔴 VENTA en {precio:.2f}. Resultado: {emoji} {resultado*100:.2f}% | Balance: ${self.balance_actual:.2f}")
            costo_fee = self.balance_actual * comision
            self.balance_actual -= costo_fee # <-- Nos cobramos la salida
