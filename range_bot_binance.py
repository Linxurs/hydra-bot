#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║     Range Trading Bot — Binance Futures BTC/USDT             ║
║     Estrategia: Comprar soporte / Vender resistencia         ║
╚══════════════════════════════════════════════════════════════╝

Instalación:
    pip install python-binance customtkinter matplotlib

Uso:
    python range_bot_binance.py

Modos:
    - Paper Trading: simula operaciones sin dinero real (default)
    - Testnet:       opera en testnet de Binance Futures
    - Real:          opera con dinero real (¡usá con cuidado!)
"""

import json
import math
import os
import random
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

# ─── Verificar dependencias ──────────────────────────────────────────────────
MISSING = []
try:
    import customtkinter as ctk
except ImportError:
    MISSING.append("customtkinter")

try:
    import matplotlib

    matplotlib.use("TkAgg")
    import matplotlib.ticker as mticker
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    MPL_OK = True
except ImportError:
    MPL_OK = False
    MISSING.append("matplotlib")

try:
    from binance import ThreadedWebsocketManager
    from binance.client import Client

    BIN_OK = True
except ImportError:
    BIN_OK = False

if MISSING:
    print(f"\n[ERROR] Faltan dependencias: {', '.join(MISSING)}")
    print(f"Ejecutá: pip install {' '.join(MISSING)}")
    sys.exit(1)

import tkinter as tk
from tkinter import messagebox

# ─── Constantes ──────────────────────────────────────────────────────────────
APP_TITLE = "Range Trading Bot — Binance Futures"
CONFIG_FILE = Path("bot_config.json")
LOG_FILE = Path("trades_log.json")
VERSION = "1.0.0"

COLORS = {
    "green": "#4CAF7D",
    "green_dim": "#2d5a40",
    "red": "#E05252",
    "red_dim": "#5c2a2a",
    "amber": "#F5A623",
    "blue": "#4A9EFF",
    "blue_dim": "#1a3a5c",
    "bg_dark": "#1a1a2e",
    "bg_card": "#16213e",
    "bg_input": "#0f3460",
    "text_dim": "#8899aa",
    "border": "#2a3a4a",
}

DEFAULT_CONFIG = {
    "api_key": "",
    "api_secret": "",
    "use_demo": True,  # Demo Trading Binance (demo-fapi.binance.com)
    "paper_mode": True,
    "symbol": "BTCUSDT",
    "soporte": 75000.0,
    "resistencia": 80000.0,
    "stop_loss_pct": 2.5,
    "entry_zone_pct": 0.5,
    "capital": 250.0,
    "leverage": 3,
    "demo_mode": not BIN_OK,
}

# Endpoints oficiales de Binance Demo Trading (reemplazó al viejo testnet)
DEMO_REST_URL = "https://demo-fapi.binance.com"  # Demo Futures REST
LIVE_REST_URL = "https://fapi.binance.com"  # Futures real
DEMO_WS_MARKET = "wss://fstream.binancefuture.com"  # WS mercado (demo y real)
LIVE_WS_MARKET = "wss://fstream.binance.com"  # WS mercado real


# ─── Estados del bot ─────────────────────────────────────────────────────────
class BotState:
    STOPPED = "DETENIDO"
    WATCHING = "OBSERVANDO"
    IN_LONG = "EN LONG  ▲"
    IN_SHORT = "EN SHORT ▼"


# ─── Utilidades ──────────────────────────────────────────────────────────────
def fmt_price(n):
    return f"${n:,.2f}"


def fmt_pnl(n):
    sign = "+" if n >= 0 else ""
    return f"{sign}${n:,.2f}"


def now_str():
    return datetime.now().strftime("%H:%M:%S")


def load_json(path, default):
    try:
        if path.exists():
            with open(path) as f:
                return {**default, **json.load(f)}
    except Exception:
        pass
    return dict(default)


def save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


# ─── Motor de trading ─────────────────────────────────────────────────────────
class BotEngine:
    """Toda la lógica de trading corre en hilos separados."""

    def __init__(self, cfg, on_price, on_state, on_trade, on_log):
        self.cfg = cfg
        self.on_price = on_price
        self.on_state = on_state
        self.on_trade = on_trade
        self.on_log = on_log

        self.active = False
        self.state = BotState.STOPPED
        self.client = None
        self.twm = None
        # GRID STATE
        self.grid_levels = []
        self.active_orders = {}
        self.last_level_idx = None
        self.capital_per_order = 0.0

        self.balance = 250.0
        self.total_pnl = 0.0
        self.trade_count = 0
        self.win_count = 0
        self.current_price = None
        self.price_history = deque(maxlen=300)
        self.candles = deque(maxlen=60)  # 60 velas de 1 min
        self._current_candle = None

        self.used_weight = 0
        self.funding_rate = 0.0
        self._demo_thread = None
        self._poll_thread = None
        self._lock = threading.Lock()

    # ── Conexión ──────────────────────────────────────────────────────────────
    def _signed_request(self, method, endpoint, params=None):
        """Envía requests firmados con monitoreo de peso (patch_pro optimization)."""
        import hashlib as _hash
        import hmac as _hmac
        from urllib.parse import urlencode

        import requests as _req

        base = getattr(self, "_base_url", DEMO_REST_URL)
        url = f"{base}/fapi/v1/{endpoint}"
        p = params or {}
        p["timestamp"] = int(time.time() * 1000)
        query = urlencode(p)
        sig = _hmac.new(
            self.cfg["api_secret"].encode(), query.encode(), _hash.sha256
        ).hexdigest()

        full_url = f"{url}?{query}&signature={sig}"
        headers = {"X-MBX-APIKEY": self.cfg["api_key"]}

        try:
            resp = _req.request(method, full_url, headers=headers, timeout=10)

            # Monitoreo de Pesos (X-MBX-USED-WEIGHT-1M) según patch_pro.py
            w = resp.headers.get("X-MBX-USED-WEIGHT-1M")
            if w:
                self.used_weight = int(w)
                if self.used_weight > 4800:  # 80% del límite (6000)
                    self.on_log(f"⚠  API WEIGHT CRÍTICO: {self.used_weight}/6000")

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 10))
                self.on_log(f"🚫 RATE LIMIT (429). Esperando {retry_after}s...")
                time.sleep(retry_after)
                return {}

            return resp.json()
        except Exception as e:
            self.on_log(f"✗ Error de red: {e}")
            return {}

    def _fetch_funding(self):
        """Obtiene la tasa de fondeo actual (Funding Rate Arbitrage info)."""
        if not self.client and not BIN_OK:
            return
        try:
            res = self._signed_request(
                "GET", "premiumIndex", {"symbol": self.cfg["symbol"]}
            )
            if res and "lastFundingRate" in res:
                self.funding_rate = float(res["lastFundingRate"])
        except:
            pass

    def connect(self):
        api_key = self.cfg["api_key"].strip()
        api_secret = self.cfg["api_secret"].strip()

        # Si no hay API o es modo demo, usamos el simulador interno para asegurar actividad
        if self.cfg["demo_mode"] or not api_key:
            self.on_log("ℹ  Modo simulado activo — Usando generador de precios interno")
            self._start_demo()  # Generador de precios (onda senoidal + ruido)
            return True

        if not BIN_OK:
            self.on_log("⚠  python-binance no instalado. Usando simulador.")
            self._start_demo()
            return True

        use_demo = self.cfg.get("use_demo", True)
        base_url = DEMO_REST_URL if use_demo else LIVE_REST_URL

        try:
            # Creamos el cliente SIN testnet=True (ese flag usa URLs viejas)
            # y sobreescribimos manualmente las URLs de Futures
            self.client = Client(api_key, api_secret, testnet=False)
            self.client.FUTURES_URL = f"{base_url}/fapi"
            self.client.FUTURES_DATA_URL = f"{base_url}/futures/data"

            # Test de conectividad usando requests directo al endpoint correcto
            import requests as _req

            r = _req.get(f"{base_url}/fapi/v1/ping", timeout=8)
            r.raise_for_status()

            tag = (
                " [DEMO — demo-fapi.binance.com]"
                if use_demo
                else " [REAL ⚠ — fapi.binance.com]"
            )
            self.on_log(f"✓  Conectado a Binance Futures{tag}")
            self._base_url = base_url
            self._start_ws_public()
            return True

        except Exception as e:
            self.on_log(f"✗  Error de conexión: {e}")
            self.on_log("ℹ  Activando modo simulado como fallback")
            self._start_ws_public()
            return False

    def disconnect(self):
        if self.twm:
            try:
                self.twm.stop()
            except Exception:
                pass
            self.twm = None
        self.client = None

    # ── WebSocket público de mercado (funciona para demo y real) ──────────────
    def _start_ws_public(self):
        """Conecta al WS público de Binance Futures para precio en tiempo real.
        Usa wss://fstream.binancefuture.com para demo y wss://fstream.binance.com para real."""
        use_demo = self.cfg.get("use_demo", True) or self.cfg.get("demo_mode", True)
        ws_url = (
            f"{DEMO_WS_MARKET}/stream?streams={self.cfg['symbol'].lower()}@aggTrade"
        )
        self.on_log(f"ℹ  Conectando WS de mercado: {ws_url[:50]}...")
        self._ws_running = True

        def loop():
            import websocket

            def on_message(ws, msg):
                try:
                    d = json.loads(msg)
                    # aggTrade stream viene en {"data": {...}} o directo
                    data = d.get("data", d)
                    price = float(data.get("p", 0))
                    if price > 0:
                        self._process_price(price)
                except Exception:
                    pass

            def on_error(ws, err):
                self.on_log(f"⚠  WS error: {err} — cambiando a polling REST")
                self._start_poll_rest()

            def on_close(ws, *args):
                if self._ws_running:
                    time.sleep(3)
                    self.on_log("↻  Reconectando WS...")
                    loop()

            ws_app = websocket.WebSocketApp(
                ws_url, on_message=on_message, on_error=on_error, on_close=on_close
            )
            ws_app.run_forever(ping_interval=20, ping_timeout=10)

        t = threading.Thread(target=loop, daemon=True)
        t.start()

    # ── Polling REST como fallback ─────────────────────────────────────────────
    def _start_poll_rest(self):
        """Polling al endpoint público de Binance cada 2s. No requiere API key."""
        use_demo = self.cfg.get("use_demo", True)
        base = DEMO_REST_URL if use_demo else LIVE_REST_URL
        sym = self.cfg["symbol"]

        def loop():
            import requests as _req

            self.on_log("ℹ  Polling REST activo (actualiza c/2s)")
            while True:
                try:
                    url = f"{base}/fapi/v1/ticker/price?symbol={sym}"
                    r = _req.get(url, timeout=5)
                    data = r.json()
                    price = float(data.get("price", 0))
                    if price > 0:
                        self._process_price(price)
                except Exception:
                    pass
                time.sleep(2)

        t = threading.Thread(target=loop, daemon=True)
        t.start()

    # ── Órdenes reales usando requests + HMAC (compatible con demo-fapi) ───────
    def _signed_request(self, method, endpoint, params=None):
        """Envía requests firmados al endpoint correcto (demo o real)."""
        import hashlib as _hash
        import hmac as _hmac
        from urllib.parse import urlencode

        import requests as _req

        base = getattr(self, "_base_url", DEMO_REST_URL)
        url = f"{base}/fapi/v1/{endpoint}"
        p = params or {}
        p["timestamp"] = int(time.time() * 1000)
        query = urlencode(p)
        sig = _hmac.new(
            self.cfg["api_secret"].encode(), query.encode(), _hash.sha256
        ).hexdigest()
        full_url = f"{url}?{query}&signature={sig}"
        headers = {"X-MBX-APIKEY": self.cfg["api_key"]}

        if method == "GET":
            return _req.get(full_url, headers=headers, timeout=8).json()
        elif method == "POST":
            return _req.post(full_url, headers=headers, timeout=8).json()
        elif method == "DELETE":
            return _req.delete(full_url, headers=headers, timeout=8).json()

    def _start_demo(self):
        def loop():
            s = self.cfg["soporte"]
            r = self.cfg["resistencia"]
            mid = (s + r) / 2
            amp = (r - s) / 2 * 0.75
            price = mid
            t = 0
            while True:
                noise = random.gauss(0, 150)
                trend = amp * math.sin(t * 0.03)
                price = mid + trend + noise
                price = max(s * 0.96, min(r * 1.04, price))
                self._process_price(round(price, 2))
                t += 1
                time.sleep(1.5)

        self._demo_thread = threading.Thread(target=loop, daemon=True)
        self._demo_thread.start()

    def _process_price(self, price):
        now = time.time()
        self.current_price = price
        self.price_history.append((now, price))
        
        # VELOCIDAD HFT: Velas de 15 segundos para el sibarita
        interval = 15 
        minute_ts = int(now // interval) * interval
        if not self._current_candle or self._current_candle["t"] != minute_ts:
            if self._current_candle:
                self.candles.append(self._current_candle)
            self._current_candle = {"t": minute_ts, "o": price, "h": price, "l": price, "c": price}
        else:
            self._current_candle["h"] = max(self._current_candle["h"], price)
            self._current_candle["l"] = min(self._current_candle["l"], price)
            self._current_candle["c"] = price

        self.on_price(price)
        if self.active:
            # GATILLO INSTANTÁNEO: Verificación de niveles en cada parpadeo
            if self.last_level_idx is None:
                self._init_grid(price)
            self._check_logic(price)

    # ── Lógica de trading ─────────────────────────────────────────────────────
    def _init_grid(self, current_price):
        s = self.cfg["soporte"]
        r = self.cfg["resistencia"]

        # DENSIDAD EXTREMA: Captura micro-movimientos (HFT Style)
        # Reducimos el paso a la mitad de lo solicitado para "estrellas en el cielo"
        ez = (self.cfg["entry_zone_pct"] / 100) * 0.5

        base_price = current_price if current_price else (s + r) / 2
        grid_step = base_price * ez
        if grid_step <= 0:
            grid_step = 2  # Paso mínimo agresivo

        levels_count = int((r - s) / grid_step)
        # Forzamos alta densidad: mínimo 50 niveles para flujo constante de trades
        levels_count = max(50, levels_count)
        grid_step = (r - s) / levels_count

        self.grid_levels = [s + i * grid_step for i in range(levels_count + 1)]
        self.active_orders = {}

        # CRITERIO DE KELLY (Simplificado para HFT): f* = (bp - q) / b
        # Asumimos win_rate del 60% (p=0.6) y b=1 (reward/risk en grid es ~1)
        # f* = (1*0.6 - 0.4) / 1 = 0.2 -> Arriesgamos hasta el 20% del balance por nivel de grid
        win_rate_est = max(
            0.55, (self.win_count / self.trade_count) if self.trade_count > 10 else 0.6
        )
        kelly_f = win_rate_est - (1 - win_rate_est)

        actual_capital = self.balance * kelly_f
        self.capital_per_order = actual_capital / (
            levels_count * 0.2
        )  # Factor de solapamiento pro

        self.on_log(
            f"🚀 MODO DIOS: {len(self.grid_levels)} niveles. Kelly F: {kelly_f:.2f}. "
            f"Capital en juego: ${actual_capital:,.2f}"
        )

        # Encontrar nivel actual antes de sembrar
        distances = [abs(current_price - lvl) for lvl in self.grid_levels]
        self.last_level_idx = distances.index(min(distances))

        # SEMBRAR EL GRID COMPLETO
        for i, lvl_price in enumerate(self.grid_levels):
            if i < self.last_level_idx:
                # Niveles por debajo: Abrimos LONG
                self._open_grid_order(i, "long", lvl_price)
            elif i > self.last_level_idx:
                # Niveles por encima: Abrimos SHORT
                self._open_grid_order(i, "short", lvl_price)

        self.on_log(
            f"✓ Grid sembrado con {len(self.active_orders)} posiciones iniciales."
        )

    def _update_state(self):
        net_exposure = 0.0
        for p in self.active_orders.values():
            if p["type"] == "long":
                net_exposure += p["capital"] * p["leverage"]
            else:
                net_exposure -= p["capital"] * p["leverage"]

        if abs(net_exposure) < 1.0:
            self.state = BotState.WATCHING
        elif net_exposure > 0:
            self.state = f"GRID (Net: +${abs(net_exposure):,.0f})"
        else:
            self.state = f"GRID (Net: -${abs(net_exposure):,.0f})"

        self.on_state(self.state, None, self._stats())

    def _open_grid_order(self, idx, pos_type, price):
        lev = self.cfg["leverage"]
        order = {
            "type": pos_type,
            "entry": price,
            "capital": self.capital_per_order,
            "leverage": lev,
            "idx": idx,
        }
        self.active_orders[idx] = order
        action = "LONG" if pos_type == "long" else "SHORT"

        if not self.cfg["paper_mode"] and self.client:
            side = "BUY" if pos_type == "long" else "SELL"
            self._open_real_market(side, price, self.capital_per_order, lev)

        self.on_trade(
            {"action": action, "price": price, "pnl": None, "time": now_str()}
        )
        self._update_state()

    def _close_grid_order(self, idx, price, reason):
        if idx not in self.active_orders:
            return
        p = self.active_orders.pop(idx)

        diff = (price - p["entry"]) if p["type"] == "long" else (p["entry"] - price)
        pnl = (diff / p["entry"]) * p["capital"] * p["leverage"]

        self.balance += pnl
        self.total_pnl += pnl
        self.trade_count += 1
        if pnl > 0:
            self.win_count += 1

        if not self.cfg["paper_mode"] and self.client:
            side = "SELL" if p["type"] == "long" else "BUY"
            self._open_real_market(
                side, price, p["capital"], p["leverage"], reduce_only=True
            )

        self.on_trade({"action": reason, "price": price, "pnl": pnl, "time": now_str()})
        self._update_state()

    def _open_real_market(self, side, entry, cap, lev, reduce_only=False):
        try:
            sym = self.cfg["symbol"]
            qty = round((cap * lev) / entry, 3)
            if qty <= 0:
                return
            if not reduce_only:
                self._signed_request(
                    "POST", "leverage", {"symbol": sym, "leverage": lev}
                )

            params = {"symbol": sym, "side": side, "type": "MARKET", "quantity": qty}
            if reduce_only:
                params["reduceOnly"] = "true"

            r = self._signed_request("POST", "order", params)
            self.on_log(
                f"✓  Orden {'REDUCE ' if reduce_only else ''}MARKET {side} {qty} @ ~{fmt_price(entry)}"
            )
        except Exception as e:
            self.on_log(f"✗  Error orden real: {e}")

    def _check_logic(self, price):
        with self._lock:
            s = self.cfg["soporte"]
            r = self.cfg["resistencia"]
            slp = self.cfg["stop_loss_pct"] / 100

            # Global Stop Loss
            if price <= s * (1 - slp) or price >= r * (1 + slp):
                if self.active_orders:
                    for idx in list(self.active_orders.keys()):
                        self._close_grid_order(idx, price, "SL ✗")
                    self.on_log("⚠  STOP LOSS GLOBAL ALCANZADO. Deteniendo bot.")
                    self.stop()
                return

            if self.last_level_idx is None:
                return

            # Process crossings
            while True:
                if (
                    self.last_level_idx > 0
                    and price <= self.grid_levels[self.last_level_idx - 1]
                ):
                    self.last_level_idx -= 1
                    idx = self.last_level_idx
                    if (
                        idx + 1 in self.active_orders
                        and self.active_orders[idx + 1]["type"] == "short"
                    ):
                        self._close_grid_order(idx + 1, price, "TP ✓")
                    if idx not in self.active_orders:
                        self._open_grid_order(idx, "long", price)
                elif (
                    self.last_level_idx < len(self.grid_levels) - 1
                    and price >= self.grid_levels[self.last_level_idx + 1]
                ):
                    self.last_level_idx += 1
                    idx = self.last_level_idx
                    if (
                        idx - 1 in self.active_orders
                        and self.active_orders[idx - 1]["type"] == "long"
                    ):
                        self._close_grid_order(idx - 1, price, "TP ✓")
                    if idx not in self.active_orders:
                        self._open_grid_order(idx, "short", price)
                else:
                    break

    def _stats(self):
        wr = (self.win_count / self.trade_count * 100) if self.trade_count else 0
        return {
            "balance": self.balance,
            "total_pnl": self.total_pnl,
            "trade_count": self.trade_count,
            "win_rate": wr,
            "weight": self.used_weight,
            "funding": self.funding_rate,
        }

    # ── Control del bot ───────────────────────────────────────────────────────
    def _start_funding_fetcher(self):
        def loop():
            while True:
                self._fetch_funding()
                time.sleep(30)

        threading.Thread(target=loop, daemon=True).start()

    def start(self):
        self.active = True
        self._start_funding_fetcher()
        if self.current_price:
            self._init_grid(self.current_price)
        else:
            self.last_level_idx = None
        self._update_state()
        self.on_log("▶  Bot iniciado — Grid Activo")

    def stop(self):
        self.active = False
        self.state = BotState.STOPPED
        self._update_state()
        self.on_log("⏹  Bot detenido")

    def reset_stats(self):
        self.balance = 250.0
        self.total_pnl = 0.0
        self.trade_count = 0
        self.win_count = 0
        self._update_state()
        self.on_log("↺  Estadísticas reiniciadas")


# ─── Aplicación GUI ───────────────────────────────────────────────────────────
class RangeBotApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(APP_TITLE)
        self.geometry("1280x820")
        self.minsize(1100, 700)

        self.cfg = load_json(CONFIG_FILE, DEFAULT_CONFIG)
        self.trade_log = load_json(LOG_FILE, {"trades": []}).get("trades", [])
        self.engine = None
        self._connected = False

        self._price_history = deque(maxlen=120)
        self._entry_markers = []  # [(time_idx, price, type)]
        self._price_vals = deque(maxlen=120)

        self._build_ui()
        self._schedule_chart_update()

    # ─── Construcción de la UI ────────────────────────────────────────────────
    def _build_ui(self):
        # Fuente mono para números
        self.font_mono = ctk.CTkFont(family="Courier New", size=13)
        self.font_mono_l = ctk.CTkFont(family="Courier New", size=22, weight="bold")
        self.font_mono_m = ctk.CTkFont(family="Courier New", size=16, weight="bold")
        self.font_label = ctk.CTkFont(size=11)
        self.font_head = ctk.CTkFont(size=13, weight="bold")

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self._build_header()
        self._build_left_panel()
        self._build_statusbar()
        self._build_right_panel()

    # ── Header ────────────────────────────────────────────────────────────────
    def _build_header(self):
        hdr = ctk.CTkFrame(
            self, height=52, corner_radius=0, fg_color=("#0d1117", "#0d1117")
        )
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew")
        hdr.grid_propagate(False)

        ctk.CTkLabel(
            hdr,
            text=f"  ◈  Range Trading Bot  v{VERSION}",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLORS["blue"],
        ).pack(side="left", padx=16)

        self.lbl_conn_dot = ctk.CTkLabel(
            hdr, text="●", font=ctk.CTkFont(size=14), text_color=COLORS["text_dim"]
        )
        self.lbl_conn_dot.pack(side="right", padx=(0, 4))

        self.lbl_conn = ctk.CTkLabel(
            hdr,
            text="Sin conectar",
            font=self.font_label,
            text_color=COLORS["text_dim"],
        )
        self.lbl_conn.pack(side="right", padx=(0, 16))

        self.lbl_mode = ctk.CTkLabel(
            hdr,
            text="PAPER TRADING",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["amber"],
            fg_color=("#2a1f00", "#2a1f00"),
            corner_radius=4,
            padx=8,
            pady=2,
        )
        self.lbl_mode.pack(side="right", padx=8)

    # ── Panel izquierdo ───────────────────────────────────────────────────────
    def _build_left_panel(self):
        left = ctk.CTkFrame(
            self, width=310, corner_radius=0, fg_color=("#111827", "#111827")
        )
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 0))
        left.grid_propagate(False)
        left.grid_rowconfigure(99, weight=1)

        scrollable = ctk.CTkScrollableFrame(left, fg_color="transparent", width=295)
        scrollable.pack(fill="both", expand=True, padx=6, pady=6)

        self._section_api(scrollable)
        self._section_range(scrollable)
        self._section_risk(scrollable)
        self._section_mode(scrollable)
        self._section_controls(scrollable)

    def _sep(self, parent):
        ctk.CTkFrame(parent, height=1, fg_color=COLORS["border"], corner_radius=0).pack(
            fill="x", pady=8
        )

    def _section_header(self, parent, title, icon=""):
        ctk.CTkLabel(
            parent,
            text=f" {icon}  {title}",
            font=self.font_head,
            text_color=COLORS["blue"],
            anchor="w",
        ).pack(fill="x", pady=(4, 2))

    def _field(self, parent, label, var, placeholder="", is_password=False):
        ctk.CTkLabel(
            parent,
            text=label,
            font=self.font_label,
            text_color=COLORS["text_dim"],
            anchor="w",
        ).pack(fill="x", pady=(4, 0))
        kw = {"show": "●"} if is_password else {}
        entry = ctk.CTkEntry(
            parent,
            textvariable=var,
            placeholder_text=placeholder,
            font=self.font_mono,
            height=32,
            **kw,
        )
        entry.pack(fill="x", pady=(0, 2))
        return entry

    def _section_api(self, p):
        self._section_header(p, "Conexión Binance", "⛓")

        self.var_api_key = tk.StringVar(value=self.cfg.get("api_key", ""))
        self.var_api_secret = tk.StringVar(value=self.cfg.get("api_secret", ""))
        self.var_use_demo = tk.BooleanVar(value=self.cfg.get("use_demo", True))
        self.var_demo = tk.BooleanVar(value=self.cfg.get("demo_mode", not BIN_OK))

        self._field(p, "API Key", self.var_api_key, "Generá en demo.binance.com → API")
        self._field(
            p, "API Secret", self.var_api_secret, "xxxxxxxxxxxxxxxx", is_password=True
        )

        ctk.CTkLabel(
            p,
            text="  ⓘ  Obtené tus keys en demo.binance.com → API Management",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["amber"],
            wraplength=270,
            justify="left",
        ).pack(fill="x", pady=(0, 4))

        frame_opts = ctk.CTkFrame(p, fg_color="transparent")
        frame_opts.pack(fill="x", pady=4)
        ctk.CTkCheckBox(
            frame_opts,
            text="Demo Trading\n(demo-fapi.binance.com)",
            variable=self.var_use_demo,
            font=ctk.CTkFont(size=11),
            width=160,
            fg_color=COLORS["blue_dim"],
        ).pack(side="left")
        ctk.CTkCheckBox(
            frame_opts,
            text="Sin API\n(simulado)",
            variable=self.var_demo,
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=8)

        self.btn_connect = ctk.CTkButton(
            p,
            text="⚡  Conectar",
            height=36,
            command=self._on_connect,
            fg_color=COLORS["blue_dim"],
            hover_color=COLORS["blue"],
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.btn_connect.pack(fill="x", pady=(4, 0))
        self._sep(p)

    def _section_range(self, p):
        self._section_header(p, "Configuración del Rango", "📊")

        self.var_soporte = tk.StringVar(value=str(self.cfg.get("soporte", 75000)))
        self.var_resistencia = tk.StringVar(
            value=str(self.cfg.get("resistencia", 80000))
        )
        self.var_symbol = tk.StringVar(value=self.cfg.get("symbol", "BTCUSDT"))

        self._field(p, "Par de trading", self.var_symbol, "BTCUSDT")
        self._field(p, "Soporte (USD)", self.var_soporte, "75000")
        self._field(p, "Resistencia (USD)", self.var_resistencia, "85000")
        self._sep(p)

    def _section_risk(self, p):
        self._section_header(p, "Gestión del Riesgo", "🛡")

        self.var_sl = tk.StringVar(value=str(self.cfg.get("stop_loss_pct", 2.5)))
        self.var_ez = tk.StringVar(value=str(self.cfg.get("entry_zone_pct", 0.5)))
        self.var_cap = tk.StringVar(value=str(self.cfg.get("capital", 250)))
        self.var_lev = tk.IntVar(value=self.cfg.get("leverage", 3))

        self._field(p, "Stop Loss (%)", self.var_sl, "2.5")
        self._field(p, "Zona de entrada (%)", self.var_ez, "0.5")
        self._field(p, "Capital por trade (USDT)", self.var_cap, "250")
        self._field(p, "Apalancamiento (x)", self.var_lev, "3")

        # Slider apalancamiento (Aumentado a 50x para máxima rentabilidad)
        ctk.CTkLabel(
            p,
            text=f"Lev: 1x  ──────────── 50x",
            font=self.font_label,
            text_color=COLORS["text_dim"],
            anchor="w",
        ).pack(fill="x")
        self.slider_lev = ctk.CTkSlider(
            p,
            from_=1,
            to=50,
            number_of_steps=49,
            variable=self.var_lev,
            command=self._on_lev_slide,
        )
        self.slider_lev.pack(fill="x", pady=(0, 4))
        self.lbl_lev_val = ctk.CTkLabel(
            p,
            text=f"  Apalancamiento actual: {self.var_lev.get()}x",
            font=self.font_label,
            text_color=COLORS["amber"],
        )
        self.lbl_lev_val.pack(fill="x")
        self._sep(p)

    def _section_mode(self, p):
        self._section_header(p, "Modo de operación", "⚙")
        self.var_paper = tk.BooleanVar(value=self.cfg.get("paper_mode", True))

        frame = ctk.CTkFrame(p, fg_color=("#1e2a3a", "#1e2a3a"), corner_radius=8)
        frame.pack(fill="x", pady=4)
        ctk.CTkRadioButton(
            frame,
            text="📝 Paper Trading (simulado)",
            variable=self.var_paper,
            value=True,
            font=self.font_label,
            command=self._update_mode_label,
        ).pack(anchor="w", padx=12, pady=(8, 4))
        ctk.CTkRadioButton(
            frame,
            text="💰 Real Money (cuidado!)",
            variable=self.var_paper,
            value=False,
            font=self.font_label,
            command=self._update_mode_label,
            fg_color=COLORS["red"],
        ).pack(anchor="w", padx=12, pady=(0, 8))
        self._sep(p)

    def _section_controls(self, p):
        self._section_header(p, "Control del Bot", "🤖")

        self.btn_start = ctk.CTkButton(
            p,
            text="▶   INICIAR BOT",
            height=42,
            command=self._on_start,
            fg_color=COLORS["green_dim"],
            hover_color=COLORS["green"],
            font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled",
        )
        self.btn_start.pack(fill="x", pady=(0, 6))

        self.btn_stop = ctk.CTkButton(
            p,
            text="⏹   DETENER BOT",
            height=42,
            command=self._on_stop,
            fg_color=COLORS["red_dim"],
            hover_color=COLORS["red"],
            font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled",
        )
        self.btn_stop.pack(fill="x", pady=(0, 6))

        self.btn_reset = ctk.CTkButton(
            p,
            text="↺  Reiniciar estadísticas",
            height=32,
            command=self._on_reset,
            fg_color="transparent",
            hover_color=COLORS["border"],
            font=self.font_label,
            border_width=1,
            border_color=COLORS["border"],
            state="disabled",
        )
        self.btn_reset.pack(fill="x", pady=(0, 6))

        self.btn_save = ctk.CTkButton(
            p,
            text="💾  Guardar configuración",
            height=32,
            command=self._on_save_config,
            fg_color="transparent",
            hover_color=COLORS["border"],
            font=self.font_label,
            border_width=1,
            border_color=COLORS["border"],
        )
        self.btn_save.pack(fill="x")

    # ── Panel derecho ─────────────────────────────────────────────────────────
    def _build_right_panel(self):
        right = ctk.CTkFrame(self, corner_radius=0, fg_color=("#0d1117", "#0d1117"))
        right.grid(row=1, column=1, sticky="nsew", padx=0)
        right.grid_rowconfigure(1, weight=1)
        right.grid_rowconfigure(2, weight=0)
        right.grid_rowconfigure(3, weight=0)
        right.grid_columnconfigure(0, weight=1)

        self._build_price_bar(right)
        self._build_chart(right)
        self._build_stats_row(right)
        self._build_log_panel(right)

    def _build_price_bar(self, parent):
        bar = ctk.CTkFrame(
            parent, height=90, corner_radius=0, fg_color=("#111827", "#111827")
        )
        bar.grid(row=0, column=0, sticky="ew", padx=0)
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)

        # Precio grande
        price_frame = ctk.CTkFrame(bar, fg_color="transparent")
        price_frame.grid(row=0, column=0, sticky="w", padx=20, pady=8)

        ctk.CTkLabel(
            price_frame,
            text="BTC / USDT  •  FUTURES",
            font=self.font_label,
            text_color=COLORS["text_dim"],
        ).pack(anchor="w")

        self.lbl_price = ctk.CTkLabel(
            price_frame,
            text="––––",
            font=ctk.CTkFont(family="Courier New", size=34, weight="bold"),
            text_color="white",
        )
        self.lbl_price.pack(anchor="w")

        self.lbl_price_delta = ctk.CTkLabel(
            price_frame,
            text="Cargando precio...",
            font=ctk.CTkFont(family="Courier New", size=12),
            text_color=COLORS["text_dim"],
        )
        self.lbl_price_delta.pack(anchor="w")

        # Barra de rango visual
        range_frame = ctk.CTkFrame(bar, fg_color="transparent")
        range_frame.grid(row=0, column=1, sticky="ew", padx=(0, 20), pady=12)

        ctk.CTkLabel(
            range_frame,
            text="Posición en el rango",
            font=self.font_label,
            text_color=COLORS["text_dim"],
        ).pack(anchor="w")

        self.range_bar_frame = ctk.CTkFrame(
            range_frame, height=18, fg_color=("#1e2a3a", "#1e2a3a"), corner_radius=4
        )
        self.range_bar_frame.pack(fill="x", pady=(2, 4))
        self.range_bar_frame.pack_propagate(False)

        self.range_bar_fill = ctk.CTkFrame(
            self.range_bar_frame,
            height=18,
            fg_color=COLORS["green_dim"],
            corner_radius=4,
        )
        self.range_bar_fill.place(relx=0, rely=0, relwidth=0.5, relheight=1)

        self.lbl_range_pct = ctk.CTkLabel(
            range_frame, text="––", font=self.font_label, text_color=COLORS["text_dim"]
        )
        self.lbl_range_pct.pack(anchor="w")

        # Estado del bot
        self.lbl_bot_state = ctk.CTkLabel(
            bar,
            text=f"  Estado: {BotState.STOPPED}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_dim"],
            fg_color=("#0d1117", "#0d1117"),
            corner_radius=4,
            padx=8,
            pady=4,
        )
        self.lbl_bot_state.grid(row=0, column=2, sticky="e", padx=16)

    def _build_chart(self, parent):
        chart_frame = ctk.CTkFrame(
            parent, corner_radius=0, fg_color=("#0d1117", "#0d1117")
        )
        chart_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 4))

        if not MPL_OK:
            ctk.CTkLabel(
                chart_frame,
                text="matplotlib no instalado\npip install matplotlib",
                font=self.font_label,
                text_color=COLORS["text_dim"],
            ).pack(expand=True)
            self.canvas = None
            self.ax = None
            return

        self.fig = Figure(figsize=(8, 3.2), dpi=100, facecolor="#0d1117")
        self.ax = self.fig.add_subplot(111, facecolor="#111827")

        self.ax.tick_params(colors=COLORS["text_dim"], labelsize=9)
        for spine in self.ax.spines.values():
            spine.set_edgecolor(COLORS["border"])
        self.ax.set_ylabel("Precio (USDT)", color=COLORS["text_dim"], fontsize=9)
        self.ax.grid(True, color=COLORS["border"], alpha=0.4, linewidth=0.5)

        self.fig.tight_layout(pad=0.8)
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Zoom con la ruedita
        self.zoom_level = 1.0
        self.canvas.get_tk_widget().bind("<MouseWheel>", self._on_mw_scroll)

    def _on_mw_scroll(self, event):
        if event.delta > 0:
            self.zoom_level = max(0.1, self.zoom_level * 0.9)
        else:
            self.zoom_level = min(5.0, self.zoom_level * 1.1)
        self._update_chart()

    def _build_stats_row(self, parent):
        row = ctk.CTkFrame(
            parent, height=80, corner_radius=0, fg_color=("#111827", "#111827")
        )
        row.grid(row=2, column=0, sticky="ew", padx=0, pady=(0, 4))
        row.grid_propagate(False)
        row.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        def stat_card(col, label, attr, color="white"):
            f = ctk.CTkFrame(row, fg_color=("#1a2234", "#1a2234"), corner_radius=8)
            f.grid(row=0, column=col, sticky="nsew", padx=6, pady=8)
            ctk.CTkLabel(
                f, text=label, font=self.font_label, text_color=COLORS["text_dim"]
            ).pack(pady=(6, 0))
            lbl = ctk.CTkLabel(f, text="––", font=self.font_mono, text_color=color)
            lbl.pack()
            setattr(self, attr, lbl)

        stat_card(0, "Balance virtual", "lbl_balance", "white")
        stat_card(1, "P&L acumulado", "lbl_pnl", COLORS["text_dim"])
        stat_card(2, "Trades", "lbl_trades", "white")
        stat_card(3, "Win Rate", "lbl_winrate", "white")
        stat_card(4, "Posición actual", "lbl_pos", COLORS["text_dim"])
        stat_card(5, "Weight | Funding", "lbl_pro_metrics", COLORS["amber"])

    def _build_log_panel(self, parent):
        log_frame = ctk.CTkFrame(
            parent, corner_radius=0, fg_color=("#111827", "#111827")
        )
        log_frame.grid(row=3, column=0, sticky="ew", padx=0, pady=0)
        log_frame.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(log_frame, fg_color=("#0d1117", "#0d1117"), corner_radius=0)
        hdr.pack(fill="x")

        ctk.CTkLabel(
            hdr,
            text="  📋  Registro de operaciones",
            font=self.font_head,
            text_color=COLORS["blue"],
        ).pack(side="left", pady=6)

        ctk.CTkButton(
            hdr,
            text="Exportar log",
            height=26,
            width=100,
            font=self.font_label,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border"],
            command=self._export_log,
        ).pack(side="right", padx=12, pady=4)

        # Cabecera de columnas
        cols_frame = ctk.CTkFrame(
            log_frame, fg_color=("#0d1117", "#0d1117"), corner_radius=0
        )
        cols_frame.pack(fill="x")
        for txt, w in [
            ("Hora", "60"),
            ("Acción", "80"),
            ("Precio", "110"),
            ("PnL", "90"),
            ("Info", "200"),
        ]:
            ctk.CTkLabel(
                cols_frame,
                text=txt,
                font=self.font_label,
                text_color=COLORS["text_dim"],
                width=int(w),
                anchor="w",
            ).pack(side="left", padx=4)

        # Log scrollable
        self.log_text = ctk.CTkTextbox(
            log_frame,
            height=130,
            font=self.font_mono,
            fg_color=("#0d1117", "#0d1117"),
            text_color=COLORS["text_dim"],
            corner_radius=0,
            wrap="none",
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        # Populate existing log
        for entry in self.trade_log[-30:]:
            self._append_log_line(entry, save=False)

    # ─── Barra de estado inferior ─────────────────────────────────────────────
    def _build_statusbar(self):
        bar = ctk.CTkFrame(
            self, height=26, corner_radius=0, fg_color=("#0a0f1a", "#0a0f1a")
        )
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)

        self.lbl_status = ctk.CTkLabel(
            bar,
            text="  Listo. Configurá tu API key y presioná Conectar.",
            font=self.font_label,
            text_color=COLORS["text_dim"],
            anchor="w",
        )
        self.lbl_status.pack(side="left")

        ctk.CTkLabel(
            bar,
            text=f"  Range Trading Bot {VERSION}  ",
            font=self.font_label,
            text_color=COLORS["border"],
        ).pack(side="right")

    # ─── Actualización de gráfico ─────────────────────────────────────────────
    def _schedule_chart_update(self):
        self._update_chart()
        # MÁXIMA VELOCIDAD: Refresco cada 500ms para sentir el pulso del mercado
        self.after(500, self._schedule_chart_update)

    def _update_chart(self):
        if not self.ax or not self.canvas or not self.engine:
            return

        # Obtener velas (históricas + actual)
        candles = list(self.engine.candles)
        if self.engine._current_candle:
            candles.append(self.engine._current_candle)

        if not candles:
            return

        self.ax.clear()
        self.ax.set_facecolor("#0d1117")
        self.ax.tick_params(colors=COLORS["text_dim"], labelsize=9)
        self.ax.grid(True, color=COLORS["border"], alpha=0.2, linewidth=0.5)

        s = self.engine.cfg["soporte"]
        r = self.engine.cfg["resistencia"]

        # 1. TRAYECTORIA Y BANDAS (Cálculo dinámico desde N=2)
        closes = [c["c"] for c in candles]
        x_indices = range(len(candles))
        
        if len(closes) >= 2:
            import numpy as np
            # Bandas de Bollinger Adaptativas (periodo min(20, len))
            p = min(20, len(closes))
            sma = [np.mean(closes[max(0, i - (p-1)) : i + 1]) for i in range(len(closes))]
            std = [np.std(closes[max(0, i - (p-1)) : i + 1]) for i in range(len(closes))]
            upper = [sma[i] + 2 * std[i] for i in range(len(closes))]
            lower = [sma[i] - 2 * std[i] for i in range(len(closes))]
            
            # Dibujo de Bandas
            self.ax.plot(x_indices, upper, color="#3b82f6", alpha=0.4, linewidth=1, label="Bollinger")
            self.ax.plot(x_indices, lower, color="#3b82f6", alpha=0.4, linewidth=1)
            self.ax.fill_between(x_indices, lower, upper, color="#3b82f6", alpha=0.05)
            
            # EMA 7 - La 'Trayectoria' de Binance
            alpha_ema = 2 / (7 + 1)
            ema7 = [closes[0]]
            for val in closes[1:]:
                ema7.append(val * alpha_ema + ema7[-1] * (1 - alpha_ema))
            self.ax.plot(x_indices, ema7, color="#f59e0b", alpha=0.6, linewidth=1.2, label="EMA 7")

        # 2. RECORRIDO DE PRECIO (Línea continua sutil)
        self.ax.plot(x_indices, closes, color="white", alpha=0.15, linewidth=0.8)

        # 3. VELAS JAPONESAS (Sólidas y definidias)
        width = 0.6 
        for i, c in enumerate(candles):
            is_green = c["c"] >= c["o"]
            color = "#22c55e" if is_green else "#ef4444" # Colores vibrantes
            
            # Mecha - Línea sólida, no punteada
            self.ax.vlines(i, c["l"], c["h"], color=color, linewidth=1, alpha=0.6)
            
            # Cuerpo - Rectángulo sólido
            height = abs(c["c"] - c["o"])
            min_h = c["c"] * 0.00005 # Altura mínima para que no desaparezca
            draw_h = max(height, min_h)
            bottom = min(c["c"], c["o"])
            
            self.ax.add_patch(matplotlib.patches.Rectangle(
                (i - width/2, bottom), width, draw_h, 
                facecolor=color, edgecolor=color, alpha=1.0, linewidth=0
            ))

        # 4. RANGO Y GRID
        self.ax.axhline(s, color="#22c55e", linewidth=1, linestyle="-", alpha=0.3)
        self.ax.axhline(r, color="#ef4444", linewidth=1, linestyle="-", alpha=0.3)
        
        # 5. PRECIO ACTUAL (Etiqueta Flotante)
        curr_p = self.engine.current_price
        if curr_p:
            self.ax.axhline(curr_p, color="white", linewidth=0.5, alpha=0.4)
            self.ax.text(len(candles) - 0.5, curr_p, f" {curr_p:,.2f} ", 
                        color="white", weight="bold", fontsize=10,
                        bbox=dict(facecolor="#3b82f6", edgecolor="none", alpha=1.0, boxstyle="round,pad=0.3"),
                        va="center", ha="left")

        # 5. ÓRDENES ACTIVAS (Líneas de Combate)
        if hasattr(self.engine, "active_orders"):
            for p in self.engine.active_orders.values():
                c = COLORS["green"] if p["type"] == "long" else COLORS["red"]
                # Línea extendida para ver el grid sembrado
                self.ax.axhline(p["entry"], color=c, alpha=0.15, linestyle="--", linewidth=0.8)
                # Marcador agresivo
                self.ax.plot(len(candles)-1, p["entry"], ">" if p["type"] == "long" else "<", 
                            color=c, markersize=10, markeredgecolor="white", alpha=0.8)

        # 6. AUTO-ZOOM DINÁMICO (Enfoque en la acción)
        # Mostramos las últimas 40 velas para que se vean grandes y detalladas
        window = 40
        start_x = max(-1, len(candles) - window)
        end_x = len(candles) + 5
        self.ax.set_xlim(start_x, end_x)
        
        # Ajuste vertical inteligente: Centrar en el precio actual y el rango
        visible_candles = candles[-window:]
        if visible_candles:
            v_high = max(max(c["h"] for c in visible_candles), s, r)
            v_low = min(min(c["l"] for c in visible_candles), s, r)
            margin = (v_high - v_low) * 0.15
            self.ax.set_ylim(v_low - margin, v_high + margin)

        self.ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
        self.fig.tight_layout(pad=0.8)
        self.canvas.draw_idle()

    # ─── Callbacks del engine ─────────────────────────────────────────────────
    def _cb_price(self, price):
        self.after(0, self._update_price_ui, price)

    def _update_price_ui(self, price):
        prev = getattr(self, "_last_price", None)
        self._last_price = price

        color = "white"
        delta_text = ""
        if prev:
            d = price - prev
            color = COLORS["green"] if d >= 0 else COLORS["red"]
            delta_text = f"{'▲' if d >= 0 else '▼'} {'+' if d >= 0 else ''}{d:+.2f}  ({d / prev * 100:+.3f}%)"

        self.lbl_price.configure(text=f"${price:,.2f}", text_color=color)
        self.lbl_price_delta.configure(text=delta_text or "Conectando...")

        # Barra de rango
        s = float(self.var_soporte.get())
        r = float(self.var_resistencia.get())
        if r > s:
            pct = max(0, min(1, (price - s) / (r - s)))
            self.range_bar_fill.place(relx=0, rely=0, relwidth=pct, relheight=1)
            zone_color = (
                COLORS["green_dim"]
                if pct < 0.15
                else COLORS["red_dim"]
                if pct > 0.85
                else COLORS["blue_dim"]
            )
            self.range_bar_fill.configure(fg_color=zone_color)
            self.lbl_range_pct.configure(
                text=f"S ${s:,.0f}  ──  {pct * 100:.1f}%  ──  R ${r:,.0f}"
            )

    def _cb_state(self, state, position, stats):
        self.after(0, self._update_state_ui, state, position, stats)

    def _update_state_ui(self, state, position, stats):
        color_map = {
            BotState.STOPPED: COLORS["text_dim"],
            BotState.WATCHING: COLORS["amber"],
            BotState.IN_LONG: COLORS["green"],
            BotState.IN_SHORT: COLORS["red"],
        }
        text_col = color_map.get(state, COLORS["amber"])
        if "Net: +" in state:
            text_col = COLORS["green"]
        elif "Net: -" in state:
            text_col = COLORS["red"]
        self.lbl_bot_state.configure(text=f"  Estado: {state}  ", text_color=text_col)

        if stats:
            bal = stats["balance"]
            pnl = stats["total_pnl"]
            wr = stats["win_rate"]
            tc = stats["trade_count"]

            self.lbl_balance.configure(text=f"${bal:,.2f}")
            self.lbl_pnl.configure(
                text=fmt_pnl(pnl),
                text_color=COLORS["green"] if pnl >= 0 else COLORS["red"],
            )
            self.lbl_trades.configure(text=str(tc))
            self.lbl_winrate.configure(
                text=f"{wr:.1f}%",
                text_color=COLORS["green"] if wr >= 50 else COLORS["red"],
            )

        if (
            self.engine
            and hasattr(self.engine, "active_orders")
            and self.engine.active_orders
        ):
            longs = sum(
                1 for p in self.engine.active_orders.values() if p["type"] == "long"
            )
            shorts = sum(
                1 for p in self.engine.active_orders.values() if p["type"] == "short"
            )
            self.lbl_pos.configure(
                text=f"{longs} L / {shorts} S\nActivos", text_color=COLORS["amber"]
            )
        else:
            self.lbl_pos.configure(text="—", text_color=COLORS["text_dim"])

    def _cb_trade(self, trade):
        self.after(0, self._append_log_line, trade, True)

    def _append_log_line(self, trade, save=True):
        action = trade.get("action", "")
        price = trade.get("price", 0)
        pnl = trade.get("pnl")
        t = trade.get("time", "")

        color_map = {
            "LONG": COLORS["green"],
            "SHORT": COLORS["red"],
            "TP ✓": COLORS["green"],
            "SL ✗": COLORS["red"],
        }
        color = color_map.get(action, "white")

        pnl_str = fmt_pnl(pnl) if pnl is not None else "       —"
        lev = self.engine.cfg["leverage"] if self.engine else 1
        info = f"x{lev} lev" if action in ("LONG", "SHORT") else ""

        line = f"  {t:<10}  {action:<8}  ${price:>10,.2f}  {pnl_str:<12}  {info}\n"

        self.log_text.configure(state="normal")
        self.log_text.insert("1.0", line)
        self.log_text.configure(state="disabled")

        if save:
            self.trade_log.append(trade)
            save_json(LOG_FILE, {"trades": self.trade_log[-500:]})

        self.lbl_status.configure(
            text=f"  Última operación: {action} @ ${price:,.2f}"
            + (f"  →  {fmt_pnl(pnl)}" if pnl is not None else "  (abierta)")
        )

    def _cb_log(self, msg):
        self.after(0, self._status_msg, msg)

    def _status_msg(self, msg):
        self.lbl_status.configure(text=f"  {msg}")

    # ─── Acciones de botones ──────────────────────────────────────────────────
    def _on_connect(self):
        self._apply_config()
        self.btn_connect.configure(state="disabled", text="Conectando...")
        engine = BotEngine(
            cfg=self.cfg,
            on_price=self._cb_price,
            on_state=self._cb_state,
            on_trade=self._cb_trade,
            on_log=self._cb_log,
        )
        self.engine = engine

        def do_connect():
            ok = engine.connect()
            self.after(0, self._post_connect, ok)

        threading.Thread(target=do_connect, daemon=True).start()

    def _post_connect(self, ok):
        self.btn_connect.configure(state="normal", text="⚡  Reconectar")
        self._connected = True
        self.btn_start.configure(state="normal")
        self.btn_reset.configure(state="normal")

        is_demo_mode = self.cfg.get("demo_mode", True)
        use_demo = self.cfg.get("use_demo", True)

        conn_text = (
            "Simulado (sin API)"
            if is_demo_mode
            else ("Demo Trading ✓" if use_demo else "🔴 REAL MONEY")
        )
        dot_color = (
            COLORS["text_dim"]
            if is_demo_mode
            else (COLORS["green"] if use_demo else COLORS["red"])
        )
        self.lbl_conn.configure(text=conn_text)
        self.lbl_conn_dot.configure(text_color=dot_color)

    def _on_start(self):
        if not self.engine:
            messagebox.showwarning("Sin conexión", "Primero presioná Conectar.")
            return
        self._apply_config_to_engine()
        self.engine.start()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")

    def _on_stop(self):
        if self.engine:
            self.engine.stop()
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")

    def _on_reset(self):
        if messagebox.askyesno("Confirmar", "¿Reiniciar estadísticas?"):
            if self.engine:
                self.engine.reset_stats()

    def _on_save_config(self):
        self._apply_config()
        save_json(CONFIG_FILE, self.cfg)
        self.lbl_status.configure(text="  ✓  Configuración guardada en bot_config.json")

    def _on_lev_slide(self, val):
        self.lbl_lev_val.configure(text=f"  Apalancamiento actual: {int(val)}x")
        if self.engine:
            self.engine.cfg["leverage"] = int(val)

    def _update_mode_label(self):
        if self.var_paper.get():
            self.lbl_mode.configure(text="PAPER TRADING", text_color=COLORS["amber"])
        else:
            self.lbl_mode.configure(text="⚠  DINERO REAL", text_color=COLORS["red"])

    def _export_log(self):
        try:
            filename = f"trades_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            save_json(Path(filename), {"trades": self.trade_log})
            self.lbl_status.configure(text=f"  ✓  Log exportado a {filename}")
        except Exception as e:
            self.lbl_status.configure(text=f"  ✗  Error exportando: {e}")

    def _apply_config(self):
        self.cfg.update(
            {
                "api_key": self.var_api_key.get().strip(),
                "api_secret": self.var_api_secret.get().strip(),
                "use_demo": self.var_use_demo.get(),
                "demo_mode": self.var_demo.get(),
                "paper_mode": self.var_paper.get(),
                "symbol": self.var_symbol.get().strip().upper(),
                "soporte": float(self.var_soporte.get() or 75000),
                "resistencia": float(self.var_resistencia.get() or 85000),
                "stop_loss_pct": float(self.var_sl.get() or 2.5),
                "entry_zone_pct": float(self.var_ez.get() or 0.5),
                "capital": float(self.var_cap.get() or 100),
                "leverage": int(self.var_lev.get() or 3),
            }
        )

    def _apply_config_to_engine(self):
        self._apply_config()
        if self.engine:
            self.engine.cfg.update(self.cfg)


# ─── Entrada principal ────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{'=' * 60}")
    print(f"  Range Trading Bot — Binance Futures v{VERSION}")
    print(f"{'=' * 60}")
    if not BIN_OK:
        print("  ⚠  python-binance no detectado — modo demo activo")
        print("     Para trading real: pip install python-binance")
    print()

    app = RangeBotApp()
    app.mainloop()
