import ccxt
import pandas as pd
import ta
import time
import json
import logging
from requests.exceptions import ReadTimeout

# Cargar configuración
config = {
    'api_key': 'IiqdnFRGZLR9EhPDV83XOUCJpZxgQqHWUhL6nqQObrwqrmocZEzLgfHzeLLndl8F',
    'api_secret': 'hJqItlFUZh4gcUp2Lx9xUjzPp92D55LhXNPCeHx07YedS3AdWqtr4CedpYnHabM8',
    'symbol': 'BTC/USDT',
    'timeframe': '1m',
    'initial_investment': 500,
    'risk_reward_ratio': 1.5,
    'trailing_stop_loss_percent': 0.02,
    'log_file': 'trading_bot.log',
    'max_retries': 3,
    'retry_delay': 5
}

api_key = config['api_key']
api_secret = config['api_secret']
symbol = config['symbol']
timeframe = config['timeframe']
initial_investment = config['initial_investment']
risk_reward_ratio = config['risk_reward_ratio']
trailing_stop_loss_percent = config['trailing_stop_loss_percent']
log_file = config['log_file']
max_retries = config['max_retries']
retry_delay = config['retry_delay']

# Configuración de logs
logging.basicConfig(filename=log_file, level=logging.INFO, 
                    format='%(asctime)s %(levelname)s %(message)s')

class BinanceBot:
    def __init__(self, api_key, api_secret):
        self.binance = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'timeout': 20000,
            'enableRateLimit': True
        })
        self.connect()
    
    def connect(self):
        try:
            self.binance.load_time_difference()
            balance = self.binance.fetch_balance()
            logging.info("Conectado correctamente a su cuenta de Binance.")
            print("✅ Conectado correctamente a su cuenta de Binance.")
        except ccxt.NetworkError as e:
            logging.error(f'Hubo un error al conectarse a su cuenta de Binance: {e}')
            print(f"❌ Hubo un error al conectarse a su cuenta de Binance: {e}")
        except ccxt.ExchangeError as e:
            logging.error(f'Hubo un error al conectarse a su cuenta de Binance: {e}')
            print(f"❌ Hubo un error al conectarse a su cuenta de Binance: {e}")
        except Exception as e:
            logging.error(f'Hubo un error al conectarse a su cuenta de Binance: {e}')
            print(f"❌ Hubo un error al conectarse a su cuenta de Binance: {e}")

    def place_order(self, symbol, side, amount):
        try:
            if side == 'buy':
                order = self.binance.create_market_buy_order(symbol, amount)
                print(f"🛒 Orden de compra ejecutada: {amount} {symbol}")
            elif side == 'sell':
                order = self.binance.create_market_sell_order(symbol, amount)
                print(f"💰 Orden de venta ejecutada: {amount} {symbol}")
            else:
                raise ValueError("Tipo de orden no soportado. Use 'buy' o 'sell'.")
            logging.info(f'Orden {side} ejecutada con éxito: {order}')
        except ccxt.NetworkError as e:
            logging.error(f'Hubo un error al ejecutar la orden: {e}')
            print(f"❌ Hubo un error al ejecutar la orden: {e}")
        except ccxt.ExchangeError as e:
            logging.error(f'Hubo un error al ejecutar la orden: {e}')
            print(f"❌ Hubo un error al ejecutar la orden: {e}")
        except Exception as e:
            logging.error(f'Hubo un error al ejecutar la orden: {e}')
            print(f"❌ Hubo un error al ejecutar la orden: {e}")

    def monitor_for_profit_or_loss(self, symbol, amount_bought, buy_price):
        highest_price = buy_price
        while True:
            data = self.get_historical_data(symbol, '1m', 1)
            if data is not None:
                current_price = data['close'].iloc[-1]
                if current_price > highest_price:
                    highest_price = current_price

                trailing_stop_price = highest_price * (1 - trailing_stop_loss_percent)

                if current_price >= buy_price * (1 + risk_reward_ratio):  # Target profit
                    self.place_order(symbol, 'sell', amount_bought)
                    print(f"🎯 Objetivo de beneficio alcanzado: Vendiendo {amount_bought} {symbol} a {current_price}")
                    break
                elif current_price <= trailing_stop_price:  # Trailing stop loss
                    self.place_order(symbol, 'sell', amount_bought)
                    print(f"🛑 Stop loss activado: Vendiendo {amount_bought} {symbol} a {current_price}")
                    break
            time.sleep(60)

    def trading_bot(self, symbol, timeframe='1m'):
        data = self.get_historical_data(symbol, timeframe)
        if data is not None:
            data = self.apply_technical_indicators(data)
            data = self.apply_dow_theory(data)
            data = self.apply_elliot_wave_theory(data)
            data = self.apply_fibonacci_retracement(data)
            data = self.apply_supply_demand_zones(data)
            data = self.apply_wyckoff_method(data)
            data = self.apply_ict_smc(data)
            data = self.apply_smt(data)
            data = self.apply_auction_market_theory(data)
            data = self.apply_footprints(data)
            data = self.apply_heatmaps(data)
            
            buy_signals, sell_signals = self.identify_signals(data)
            base_balance, quote_balance = self.check_balance(symbol)
            
            if buy_signals.iloc[-1]:
                amount_to_buy = self.calculate_position_size(quote_balance, data['close'].iloc[-1])
                if amount_to_buy > 0:
                    self.place_order(symbol, 'buy', amount_to_buy)
                    self.monitor_for_profit_or_loss(symbol, amount_to_buy, data['close'].iloc[-1])
            elif sell_signals.iloc[-1]:
                if base_balance > 0.001:  # Arbitrary minimum balance to trade
                    self.place_order(symbol, 'sell', base_balance)
        else:
            logging.error("No se pudo obtener datos históricos.")
            print("❌ No se pudo obtener datos históricos.")
    
    def get_historical_data(self, symbol, timeframe='1m', limit=100):
        attempt = 0
        while attempt < max_retries:
            try:
                ohlcv = self.binance.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
                data = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                data['timestamp'] = pd.to_datetime(data['timestamp'], unit='ms')
                return data
            except (ccxt.NetworkError, ccxt.RequestTimeout, ReadTimeout) as e:
                logging.warning(f"Error al obtener datos históricos: {e}. Reintentando ({attempt + 1}/{max_retries})...")
                time.sleep(retry_delay)
                attempt += 1
        logging.error("No se pudo obtener datos históricos después de varios intentos.")
        return None

    def apply_technical_indicators(self, data):
        data['sma'] = ta.trend.sma_indicator(data['close'], window=14)
        data['ema'] = ta.trend.ema_indicator(data['close'], window=14)
        
        bollinger = ta.volatility.BollingerBands(data['close'], window=20, window_dev=2)
        data['bollinger_mavg'] = bollinger.bollinger_mavg()
        data['bollinger_hband'] = bollinger.bollinger_hband()
        data['bollinger_lband'] = bollinger.bollinger_lband()
        
        data['psar'] = ta.trend.psar_up(data['high'], data['low'], data['close'])
        
        data['atr'] = ta.volatility.average_true_range(data['high'], data['low'], data['close'], window=14)
        
        macd = ta.trend.MACD(data['close'])
        data['macd'] = macd.macd()
        data['macd_signal'] = macd.macd_signal()
        data['macd_diff'] = macd.macd_diff()
        
        data['rsi'] = ta.momentum.rsi(data['close'], window=14)
        
        data['kdj_k'] = ta.momentum.stoch(data['high'], data['low'], data['close'], window=14)
        data['kdj_d'] = ta.momentum.stoch_signal(data['high'], data['low'], data['close'], window=14)
        
        data['obv'] = ta.volume.on_balance_volume(data['close'], data['volume'])
        
        data['wr'] = ta.momentum.williams_r(data['high'], data['low'], data['close'], lbp=14)
        
        data['stoch_rsi'] = ta.momentum.stochrsi(data['close'], window=14)
        
        return data

    def apply_dow_theory(self, data):
        data['trend'] = 'NA'
        for i in range(1, len(data)):
            if data['close'][i] > data['close'][i-1] and data['low'][i] > data['low'][i-1]:
                data.at[i, 'trend'] = 'up'
            elif data['close'][i] < data['close'][i-1] and data['high'][i] < data['high'][i-1]:
                data.at[i, 'trend'] = 'down'
            else:
                data.at[i, 'trend'] = 'sideways'
        return data

    def apply_elliot_wave_theory(self, data):
        data['wave'] = 'NA'
        for i in range(4, len(data)):
            if data['close'][i-4] < data['close'][i-3] < data['close'][i-2] > data['close'][i-1] > data['close'][i]:
                data.at[i, 'wave'] = '5-wave-pattern'
        return data

    def apply_fibonacci_retracement(self, data):
        max_price = data['high'].max()
        min_price = data['low'].min()
        data['fib_0.236'] = min_price + (max_price - min_price) * 0.236
        data['fib_0.382'] = min_price + (max_price - min_price) * 0.382
        data['fib_0.5'] = min_price + (max_price - min_price) * 0.5
        data['fib_0.618'] = min_price + (max_price - min_price) * 0.618
        data['fib_0.786'] = min_price + (max_price - min_price) * 0.786
        return data

    def apply_supply_demand_zones(self, data):
        data['supply_zone'] = data['high'].rolling(window=20).max()
        data['demand_zone'] = data['low'].rolling(window=20).min()
        return data

    def apply_wyckoff_method(self, data):
        data['phase'] = 'NA'
        for i in range(1, len(data)):
            if data['close'][i] > data['close'][i-1] and data['volume'][i] > data['volume'][i-1]:
                data.at[i, 'phase'] = 'accumulation'
            elif data['close'][i] < data['close'][i-1] and data['volume'][i] > data['volume'][i-1]:
                data.at[i, 'phase'] = 'distribution'
        return data

    def apply_ict_smc(self, data):
        data['imbalance'] = 'NA'
        for i in range(1, len(data)):
            if data['close'][i] > data['open'][i] and data['low'][i] > data['high'][i-1]:
                data.at[i, 'imbalance'] = 'bullish_imbalance'
            elif data['close'][i] < data['open'][i] and data['high'][i] < data['low'][i-1]:
                data.at[i, 'imbalance'] = 'bearish_imbalance'
        return data

    def apply_smt(self, data):
        data['trap'] = 'NA'
        for i in range(1, len(data)):
            if data['close'][i] > data['close'][i-1] and data['volume'][i] < data['volume'][i-1]:
                data.at[i, 'trap'] = 'bull_trap'
            elif data['close'][i] < data['close'][i-1] and data['volume'][i] < data['volume'][i-1]:
                data.at[i, 'trap'] = 'bear_trap'
        return data

    def apply_auction_market_theory(self, data):
        data['value_area_high'] = data['high'].rolling(window=20).quantile(0.7)
        data['value_area_low'] = data['low'].rolling(window=20).quantile(0.3)
        return data

    def apply_footprints(self, data):
        data['footprint_buy'] = (data['close'] > data['open']).astype(int)
        data['footprint_sell'] = (data['close'] < data['open']).astype(int)
        return data

    def apply_heatmaps(self, data):
        data['heatmap'] = data['volume'].rolling(window=20).sum()
        return data

    def identify_signals(self, data):
        buy_signals = (
            (data['rsi'] < 30) &
            (data['macd'] > data['macd_signal']) &
            (data['close'] < data['bollinger_lband']) &
            (data['stoch_rsi'] < 0.2) &
            (data['wr'] < -80)
        )
        sell_signals = (
            (data['rsi'] > 70) &
            (data['macd'] < data['macd_signal']) &
            (data['close'] > data['bollinger_hband']) &
            (data['stoch_rsi'] > 0.8) &
            (data['wr'] > -20)
        )
        return buy_signals, sell_signals

    def check_balance(self, symbol):
        base_currency = symbol.split('/')[0]
        quote_currency = symbol.split('/')[1]
        balance = self.binance.fetch_balance()
        base_balance = balance['free'][base_currency]
        quote_balance = balance['free'][quote_currency]
        return base_balance, quote_balance

    def calculate_position_size(self, quote_balance, close_price):
        # Consider trading fees (0.1% for both buy and sell)
        fee_rate = 0.001
        position_size = (quote_balance / close_price) * (1 - fee_rate)
        return position_size

    def place_order(self, symbol, side, amount):
        try:
            if side == 'buy':
                order = self.binance.create_market_buy_order(symbol, amount)
            elif side == 'sell':
                order = self.binance.create_market_sell_order(symbol, amount)
            else:
                raise ValueError("Tipo de orden no soportado. Use 'buy' o 'sell'.")
            logging.info(f'Orden {side} ejecutada con éxito: {order}')
        except ccxt.NetworkError as e:
            logging.error(f'Hubo un error al ejecutar la orden: {e}')
        except ccxt.ExchangeError as e:
            logging.error(f'Hubo un error al ejecutar la orden: {e}')
        except Exception as e:
            logging.error(f'Hubo un error al ejecutar la orden: {e}')

    def monitor_for_profit_or_loss(self, symbol, amount_bought, buy_price):
        highest_price = buy_price
        while True:
            data = self.get_historical_data(symbol, '1m', 1)
            if data is not None:
                current_price = data['close'].iloc[-1]
                if current_price > highest_price:
                    highest_price = current_price

                trailing_stop_price = highest_price * (1 - trailing_stop_loss_percent)

                if current_price >= buy_price * (1 + risk_reward_ratio):  # Target profit
                    self.place_order(symbol, 'sell', amount_bought)
                    break
                elif current_price <= trailing_stop_price:  # Trailing stop loss
                    self.place_order(symbol, 'sell', amount_bought)
                    break
            time.sleep(60)

    def trading_bot(self, symbol, timeframe='1m'):
        data = self.get_historical_data(symbol, timeframe)
        if data is not None:
            data = self.apply_technical_indicators(data)
            data = self.apply_dow_theory(data)
            data = self.apply_elliot_wave_theory(data)
            data = self.apply_fibonacci_retracement(data)
            data = self.apply_supply_demand_zones(data)
            data = self.apply_wyckoff_method(data)
            data = self.apply_ict_smc(data)
            data = self.apply_smt(data)
            data = self.apply_auction_market_theory(data)
            data = self.apply_footprints(data)
            data = self.apply_heatmaps(data)
            
            buy_signals, sell_signals = self.identify_signals(data)
            base_balance, quote_balance = self.check_balance(symbol)
            
            if buy_signals.iloc[-1]:
                amount_to_buy = self.calculate_position_size(quote_balance, data['close'].iloc[-1])
                if amount_to_buy > 0:
                    self.place_order(symbol, 'buy', amount_to_buy)
                    self.monitor_for_profit_or_loss(symbol, amount_to_buy, data['close'].iloc[-1])
            elif sell_signals.iloc[-1]:
                if base_balance > 0.001:  # Arbitrary minimum balance to trade
                    self.place_order(symbol, 'sell', base_balance)
        else:
            logging.error("No se pudo obtener datos históricos.")

def main():
    bot = BinanceBot(api_key, api_secret)
    while True:
        try:
            bot.trading_bot(symbol, timeframe)
        except ccxt.base.errors.InvalidNonce as e:
            logging.error(f"Error de Nonce: {e}. Sincronizando tiempo con el servidor de Binance y reintentando...")
            print(f"⏲️ Error de Nonce: {e}. Sincronizando tiempo con el servidor de Binance y reintentando...")
            bot.binance.load_time_difference()
        except Exception as e:
            logging.error(f"Ocurrió un error: {e}")
            print(f"❌ Ocurrió un error: {e}")
        time.sleep(60 * 15)

if __name__ == "__main__":
    main()
