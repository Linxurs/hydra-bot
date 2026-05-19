import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ==========================================

# 1. CLASES DE ESTRATEGIA (LÓGICA ORIGINAL 5.0)

# ==========================================


class EstrategiaBase:
    def __init__(self, inversion_inicial=1000.0, nombre="Estrategia Generica"):
        self.nombre = nombre

        self.posicion = None

        self.precio_compra = 0.0

        self.fecha_compra = None

        self.contexto_compra = {}

        self.balance_inicial = inversion_inicial

        self.balance_actual = inversion_inicial

        self.historial_operaciones = []

        self.leverage_actual = 1.0

    def generar_indicadores(self, df):
        return df

    def proximo_paso(self, vela_actual):
        return "ESPERAR"

    def ejecutar_orden(
        self, tipo, precio, fecha, motivo="SEÑAL", leverage=1.0, contexto=None
    ):
        comision = 0.001

        if tipo == "COMPRAR" and self.posicion is None:
            self.posicion = "COMPRADO"

            self.precio_compra = precio

            self.fecha_compra = fecha

            self.leverage_actual = leverage

            self.max_precio_visto = precio

            self.contexto_compra = contexto if contexto else {}

            self.balance_antes_de_comprar = self.balance_actual

            self.cantidad_usdt_entrada = self.balance_actual * leverage

            self.balance_actual -= self.balance_actual * comision

            self.historial_operaciones.append(
                {
                    "fecha": fecha,
                    "tipo": f"COMPRA ({leverage}x)",
                    "precio": precio,
                    "leverage": leverage,
                    "cantidad_usdt": self.cantidad_usdt_entrada,
                    "contexto": self.contexto_compra,
                }
            )

        elif tipo == "VENDER" and self.posicion == "COMPRADO":
            self.posicion = None

            resultado_base = (precio - self.precio_compra) / self.precio_compra

            resultado_final = resultado_base * self.leverage_actual

            balance_previo = self.balance_actual

            self.balance_actual = self.balance_actual * (1 + resultado_final)

            self.balance_actual -= self.balance_actual * comision

            pnl_dolares = self.balance_actual - self.balance_antes_de_comprar

            self.historial_operaciones.append(
                {
                    "fecha": fecha,
                    "fecha_compra": self.fecha_compra,
                    "tipo": "VENTA",
                    "precio_venta": precio,
                    "precio_compra": self.precio_compra,
                    "balance": self.balance_actual,
                    "resultado_pct": resultado_final * 100,
                    "pnl_usd": pnl_dolares,
                    "motivo": motivo,
                    "leverage": self.leverage_actual,
                    "cantidad_usdt": self.cantidad_usdt_entrada,
                    "contexto": contexto if contexto else {},
                }
            )


class EstrategiaSuperHidra(EstrategiaBase):
    def __init__(self, inversion_inicial=1000.0):
        super().__init__(inversion_inicial, nombre="SUPER HIDRA 5.0 (ORIGINAL)")

        self.periodo_rapido = 25

        self.periodo_lento = 100

        self.umbral_adx = 40.0

        self.adx_periodo = 14

        self.stop_loss_pct = 0.07

        self.trailing_base = 0.12
        self.trailing_2 = 0.10
        self.trailing_1 = 0.02
        self.breakeven = 0.10

        self.max_precio_visto = 0.0

        self.umbral_bbw = 0.14

        self.umbral_chop = 60.0

    def generar_indicadores(self, df):
        df["ema_50"] = df["close"].ewm(span=self.periodo_rapido, adjust=False).mean()
        df["ema_200"] = df["close"].ewm(span=self.periodo_lento, adjust=False).mean()

        # ATR
        df["tr1"] = df["high"] - df["low"]
        df["tr2"] = abs(df["high"] - df["close"].shift(1))
        df["tr3"] = abs(df["low"] - df["close"].shift(1))
        df["tr"] = df[["tr1", "tr2", "tr3"]].max(axis=1)
        df["atr"] = df["tr"].rolling(window=14).mean()

        # ADX (Kaggle Math: standard EMA instead of Wilder's)
        up_move = df["high"] - df["high"].shift(1)
        down_move = df["low"].shift(1) - df["low"]
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        
        tr_s = df["tr"].ewm(span=14, adjust=False).mean()
        pdm_s = pd.Series(plus_dm).ewm(span=14, adjust=False).mean()
        mdm_s = pd.Series(minus_dm).ewm(span=14, adjust=False).mean()
        
        plus_di = 100 * pdm_s / (tr_s + 1e-10)
        minus_di = 100 * mdm_s / (tr_s + 1e-10)
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        df["adx"] = dx.ewm(span=14, adjust=False).mean()

        # RSI (Kaggle Math)
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        df["rsi"] = 100 - (100 / (1 + gain / (loss + 1e-10)))

        # BB Width (Kaggle Math)
        df["sma_20"] = df["close"].rolling(window=20).mean()
        df["std_20"] = df["close"].rolling(window=20).std(ddof=1)
        df["bb_width"] = (df["std_20"] * 4) / (df["sma_20"] + 1e-10)

        # Volume MA
        df["volumen_ma"] = df["volume"].rolling(window=20).mean()
        df["vol_ratio"] = df["volume"] / (df["volumen_ma"] + 1e-10)

        # Velocity (Not used in top config, but kept for compatibility)
        df["velocity"] = df["close"].diff(3) / (df["close"].shift(3) + 1e-10) * 100

        # EMA Macro (Kaggle Math: EMA 800 in 1h instead of resampled 4h)
        df["ema_macro"] = df["close"].ewm(span=800, adjust=False).mean()

        # Choppiness Index (CHOP)
        n_chop = 14
        tr_sum = df["tr"].rolling(window=n_chop).sum()
        max_high = df["high"].rolling(window=n_chop).max()
        min_low = df["low"].rolling(window=n_chop).min()
        df["chop"] = 100 * np.log10(tr_sum / (max_high - min_low + 1e-10)) / np.log10(n_chop)

        return df

    def proximo_paso(self, vela):
        if (
            pd.isna(vela["adx"])
            or pd.isna(vela["ema_200"])
            or pd.isna(vela.get("ema_macro", np.nan))
        ):
            return "ESPERAR"

        if self.posicion == "COMPRADO":
            self.max_precio_visto = max(self.max_precio_visto, vela["high"])

            caida_desde_max_real = (
                self.max_precio_visto - vela["low"]
            ) / self.max_precio_visto

            perdida_actual_real = (
                self.precio_compra - vela["low"]
            ) / self.precio_compra

            ganancia_actual_real = (
                vela["close"] - self.precio_compra
            ) / self.precio_compra

            umbral_liquidacion = 0.9 / self.leverage_actual

            if perdida_actual_real > umbral_liquidacion:
                return "VENDER_LIQUIDACION"

            # 1. STOP LOSS INICIAL (7%)

            if perdida_actual_real > self.stop_loss_pct:
                return "VENDER_STOP_LOSS"

            # 2. PROTECCIÓN BREAK EVEN (Si ganamos > trigger, no permitimos perder)

            if ganancia_actual_real > self.breakeven and vela["low"] < self.precio_compra * 1.002:
                return "VENDER_BREAK_EVEN"

            # 3. TRAILING ESCALONADO

            trailing_dinamico = self.trailing_1 if ganancia_actual_real > 0.20 else self.trailing_2 if ganancia_actual_real > 0.10 else self.trailing_base

            if caida_desde_max_real > trailing_dinamico:
                return "VENDER_TRAILING_STOP"

        else:
            self.max_precio_visto = 0.0

        tendencia_alcista = vela["ema_50"] > vela["ema_200"]

        fuerza_tendencia = vela["adx"] > self.umbral_adx

        volumen_fuerte = vela["volume"] > vela["volumen_ma"]

        tendencia_macro_alcista = vela["close"] > vela["ema_macro"]

        sobrecompra_fomo = vela["rsi"] > 80  # FILTRO ANTI-FOMO (Euforia Extrema)

        distancia_ema200 = (vela["close"] - vela["ema_200"]) / vela["ema_200"]

        precio_muy_caro = (
            distancia_ema200 > 0.12
        )  # FILTRO ELÁSTICO (Max 12% de la EMA 200)

        volatilidad_extrema = vela["bb_width"] > self.umbral_bbw

        mercado_choppy = vela.get("chop", 50) > self.umbral_chop

        if self.posicion is None:
            if (
                tendencia_alcista
                and tendencia_macro_alcista
                and volumen_fuerte
                and not sobrecompra_fomo
                and not precio_muy_caro
                and not volatilidad_extrema
                and not mercado_choppy
            ):
                # Ajuste de leverage por volatilidad ATR (Fase 2)
                vol_atr = vela["atr"] / (vela["close"] + 1e-10)

                mult_vol = 1.0

                if vol_atr > 0.04:
                    mult_vol = 0.5

                elif vol_atr > 0.02:
                    mult_vol = 0.8

                if vela["adx"] > 35.0:
                    lev = round(1.5 * mult_vol * 10) / 10.0

                    return f"COMPRAR_{lev}X"

                elif fuerza_tendencia:
                    lev = round(1.2 * mult_vol * 10) / 10.0

                    return f"COMPRAR_{lev}X"

                else:
                    lev = round(1.0 * mult_vol * 10) / 10.0

                    return f"COMPRAR_{lev}X"

        if self.posicion == "COMPRADO":
            if not tendencia_alcista:
                return "VENDER_CRUCE"

        return "ESPERAR"


# ==========================================

# 2. FUNCIONES DE ANALISIS Y EJECUCIÓN

# ==========================================


def calcular_metricas(balance_inicial, balance_final, historial, df_equity):
    ventas = [op for op in historial if op["tipo"] == "VENTA"]

    if not ventas:
        return {}

    resultados = [v["resultado_pct"] for v in ventas]

    df_equity["max_balance"] = df_equity["balance"].cummax()

    max_drawdown = (
        (df_equity["balance"] - df_equity["max_balance"])
        / df_equity["max_balance"]
        * 100
    ).min()

    return {
        "win_rate": (len([r for r in resultados if r > 0]) / len(ventas)) * 100,
        "max_drawdown": max_drawdown,
        "total_ops": len(ventas),
    }


def exportar_diagnostico_ia(bot, m):
    print("\n--- [REPORT] Generando REPORTE FORENSE ULTRA-DETALLADO... ---")

    ventas = [v for v in bot.historial_operaciones if v["tipo"] == "VENTA"]

    fallos = sorted(ventas, key=lambda x: x["resultado_pct"])[:50]

    logros = sorted(ventas, key=lambda x: x["resultado_pct"], reverse=True)[:50]

    beneficio_neto = bot.balance_actual - bot.balance_inicial

    beneficio_pct = (beneficio_neto / bot.balance_inicial) * 100

    lineas = [
        "==================================================",
        f"INFORME FORENSE: {bot.nombre}",
        f"Balance Final: ${bot.balance_actual:.2f}",
        f"Beneficio Neto: ${beneficio_neto:.2f} ({beneficio_pct:.2f}%)",
        f"Max Drawdown: {m.get('max_drawdown', 0):.2f}% | Win Rate: {m.get('win_rate', 0):.2f}%",
        "==================================================\n",
        "--- TOP 50 FALLOS (Peores Operaciones) ---",
    ]

    for i, op in enumerate(fallos):
        e = op["contexto"].get("entrada", {})

        s = op["contexto"].get("salida", {})

        lineas.append(
            f"FALLO #{i + 1:02d} [{op['resultado_pct']:.2f}%] | PnL: ${op['pnl_usd']:.2f} | Qty: ${op['cantidad_usdt']:.1f} | Lev: {op['leverage']}x\n"
            f"   ENTRADA: {op['fecha_compra']} @ ${op['precio_compra']:.2f} | RSI:{e.get('rsi', 0):.1f} ADX:{e.get('adx', 0):.1f} BBW:{e.get('bbw', 0):.3f} Dist200:{e.get('dist', 0):.1f}%\n"
            f"   SALIDA:  {op['fecha']} @ ${op['precio_venta']:.2f} | RSI:{s.get('rsi', 0):.1f} ADX:{s.get('adx', 0):.1f} Motivo: {op['motivo']}\n"
        )

    lineas.append("\n--- TOP 50 LOGROS (Mejores Operaciones) ---")

    for i, op in enumerate(logros):
        e = op["contexto"].get("entrada", {})

        s = op["contexto"].get("salida", {})

        lineas.append(
            f"LOGRO #{i + 1:02d} [+{op['resultado_pct']:.2f}%] | PnL: ${op['pnl_usd']:.2f} | Qty: ${op['cantidad_usdt']:.1f} | Lev: {op['leverage']}x\n"
            f"   ENTRADA: {op['fecha_compra']} @ ${op['precio_compra']:.2f} | RSI:{e.get('rsi', 0):.1f} ADX:{e.get('adx', 0):.1f} BBW:{e.get('bbw', 0):.3f} Dist200:{e.get('dist', 0):.1f}%\n"
            f"   SALIDA:  {op['fecha']} @ ${op['precio_venta']:.2f} | RSI:{s.get('rsi', 0):.1f} ADX:{s.get('adx', 0):.1f} Motivo: {op['motivo']}\n"
        )

    with open("diagnostico_ia.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))

    print("✅ Diagnóstico extendido exportado.")


def graficar_resultados(df, historial, nombre_bot):
    print(f"\n--- [GRAFICADOR] Generando visualización INTERACTIVA PRO... ---")

    plt.style.use("dark_background")

    fig, ax = plt.subplots(figsize=(16, 8))

    # 1. Gráfico de Precio y EMAs (Colores más tenues)

    ax.plot(
        df.index,
        df["close"],
        label="Precio BTC",
        color="#333333",
        alpha=0.6,
        linewidth=1,
    )

    ax.plot(
        df.index,
        df["ema_50"],
        label="EMA 50 (Rápida)",
        color="#004400",
        alpha=0.8,
        linewidth=1.5,
    )

    ax.plot(
        df.index,
        df["ema_200"],
        label="EMA 200 (Lenta)",
        color="#440044",
        alpha=0.8,
        linewidth=1.5,
    )

    # 2. Marcar Operaciones

    compras = [op for op in historial if "COMPRA" in op["tipo"]]

    ventas = [op for op in historial if op["tipo"] == "VENTA"]

    # Compras: Triángulos Blancos

    for c in compras:
        ax.scatter(
            c["fecha"],
            c["precio"],
            marker="^",
            color="#ffffff",
            s=100,
            edgecolors="gray",
            zorder=5,
        )

    # Ventas: Colores Oscuros (Verde/Rojo)

    for v in ventas:
        color_v = "#006400" if v["pnl_usd"] > 0 else "#8b0000"

        ax.scatter(
            v["fecha"],
            v["precio_venta"],
            marker="v",
            color=color_v,
            s=100,
            edgecolors="#111111",
            zorder=5,
        )

    ax.set_title(
        f"HYDRA-BOT: {nombre_bot} | SCROLL=Zoom CLICK-IZQ=Mover",
        fontsize=14,
        color="gray",
    )

    ax.legend(loc="upper left")

    ax.grid(color="#111111", linestyle="--", alpha=0.5)

    # --- LÓGICA DE ZOOM POR SCROLL ---

    def zoom(event):
        base_scale = 1.5

        cur_xlim = ax.get_xlim()

        cur_ylim = ax.get_ylim()

        xdata = event.xdata

        ydata = event.ydata

        if xdata is None or ydata is None:
            return

        if event.button == "up":
            scale_factor = 1 / base_scale

        elif event.button == "down":
            scale_factor = base_scale

        else:
            scale_factor = 1

        new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor

        new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor

        relx = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])

        rely = (cur_ylim[1] - ydata) / (cur_ylim[1] - cur_ylim[0])

        ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * relx])

        ax.set_ylim([ydata - new_height * (1 - rely), ydata + new_height * rely])

        plt.draw()

    fig.canvas.mpl_connect("scroll_event", zoom)

    # Activar modo movimiento (Pan) por defecto

    try:
        manager = plt.get_current_fig_manager()

        manager.toolbar.pan()

    except:
        pass

    print(f"📈 Ventana Abierta. USA EL SCROLL PARA ZOOM Y ARRASTRA PARA MOVER.")

    plt.show()


def ejecutar_todo():
    print("--- 1. Cargando datos originales... ---")

    df_raw = pd.read_parquet("datos/btc_usdt_1h.parquet")

    df_raw["date"] = pd.to_datetime(df_raw["timestamp"], unit="ms")

    CAPITAL = 1000.0

    bot = EstrategiaSuperHidra(inversion_inicial=CAPITAL)

    df = bot.generar_indicadores(df_raw.set_index("date").reset_index()).set_index(
        "date"
    )

    equity_curve = []

    ctx_ent_temp = {}

    print("\n" + "=" * 120)

    print(
        f"{'FECHA':<18} | {'TIPO':<10} | {'PRECIO':<9} | {'RSI':<6} | {'VOL':<5} | {'VEL':<5} | {'DIST':<5} | {'RESULTADO':<10} | {'BALANCE':<10}"
    )

    print("=" * 120)

    for i, row in df.iterrows():
        vela = row.to_dict()

        vela["date"] = i

        dec = bot.proximo_paso(vela)

        rsi = vela.get("rsi", 0)

        vol_r = vela.get("vol_ratio", 0)

        vel = vela.get("velocity", 0)

        dist = (vela["close"] - vela["ema_200"]) / (vela["ema_200"] + 1e-10) * 100

        if "COMPRAR" in dec:
            lev = float(dec.split("_")[1].replace("X", ""))

            ctx_ent_temp = {
                "rsi": vela.get("rsi"),
                "adx": vela.get("adx"),
                "bbw": vela.get("bb_width"),
                "dist": dist,
            }

            bot.ejecutar_orden(
                "COMPRAR",
                vela["close"],
                vela["date"],
                leverage=lev,
                contexto={"entrada": ctx_ent_temp},
            )

            fecha_str = vela["date"].strftime("%y-%m-%d %H:%M")

            tipo_str = f"C {lev}x"

            print(
                f"{fecha_str:<18} | {tipo_str:<10} | {vela['close']:<9.0f} | {rsi:<6.2f} | {vol_r:<5.1f} | {vel:<5.1f} | {dist:<5.1f} | {'---':<10} | {bot.balance_actual:<10.2f}"
            )

        elif "VENDER" in dec:
            balance_previo = bot.balance_actual

            ctx_sal = {"rsi": vela.get("rsi"), "adx": vela.get("adx"), "dist": dist}

            bot.ejecutar_orden(
                "VENDER",
                vela["close"],
                vela["date"],
                motivo=dec,
                contexto={"entrada": ctx_ent_temp, "salida": ctx_sal},
            )

            fecha_str = vela["date"].strftime("%y-%m-%d %H:%M")

            ganancia_neta = bot.balance_actual - balance_previo

            color = "🟢" if ganancia_neta > 0 else "🔴"

            print(
                f"{fecha_str:<18} | {'VENTA':<10} | {vela['close']:<9.0f} | {rsi:<6.2f} | {vol_r:<5.1f} | {vel:<5.1f} | {dist:<5.1f} | {color} ${ganancia_neta:<8.1f} | {bot.balance_actual:<10.2f}"
            )

        equity_curve.append({"date": vela["date"], "balance": bot.balance_actual})

    df_e = pd.DataFrame(equity_curve).set_index("date")

    m = calcular_metricas(CAPITAL, bot.balance_actual, bot.historial_operaciones, df_e)

    beneficio_neto = bot.balance_actual - CAPITAL

    beneficio_pct = (beneficio_neto / CAPITAL) * 100

    print("\n\n" + "=" * 50)

    print(f"  REPORTE FINAL: {bot.nombre}")

    print("-" * 50)

    print(f"  Balance Final:      ${bot.balance_actual:.2f}")

    print(f"  Beneficio Neto:     ${beneficio_neto:.2f} ({beneficio_pct:.2f}%)")

    print(f"  Max Drawdown:       {m.get('max_drawdown', 0):.2f}%")

    print(f"  Win Rate:           {m.get('win_rate', 0):.2f}%")

    print(f"  Operaciones:        {m.get('total_ops', 0)}")

    print("=" * 50 + "\n")

    graficar_resultados(df, bot.historial_operaciones, bot.nombre)

    exportar_diagnostico_ia(bot, m)


if __name__ == "__main__":
    ejecutar_todo()
