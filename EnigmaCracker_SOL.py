import logging
import os
import platform
import sys
import time
import requests
from bip_utils import (
    Bip39MnemonicGenerator,
    Bip39SeedGenerator,
    Bip39WordsNum,
    Bip44,
    Bip44Changes,
    Bip44Coins,
)
from dotenv import load_dotenv

# Configuración
LOG_FILE_NAME = "enigmacracker_sol.log"
ENV_FILE_NAME = "EnigmaCracker.env"
WALLETS_FILE_NAME = "sol_wallets_with_balance.txt"
BATCH_SIZE = 10            # Solana RPC suele ser más estricto con el spam
DELAY_BETWEEN_BATCHES = 1  # Segundos entre lotes

# Estado global
wallets_scanned = 0
directory = os.path.dirname(os.path.abspath(__file__))
log_file_path = os.path.join(directory, LOG_FILE_NAME)
env_file_path = os.path.join(directory, ENV_FILE_NAME)
wallets_file_path = os.path.join(directory, WALLETS_FILE_NAME)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler(sys.stdout),
    ],
)

load_dotenv(env_file_path)

def update_cmd_title():
    if platform.system() == "Windows":
        os.system(f"title EnigmaCracker_SOL.py - Wallets Scanned: {wallets_scanned}")

def generate_sol_wallet(seed):
    seed_bytes = Bip39SeedGenerator(seed).Generate()
    bip44_acc_ctx = (
        Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
        .Purpose()
        .Coin()
        .Account(0)
        .Change(Bip44Changes.CHAIN_EXT)
        .AddressIndex(0)
    )
    return bip44_acc_ctx.PublicKey().ToAddress()

def get_sol_balance(address):
    url = "https://api.mainnet-beta.solana.com"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [address]
    }
    try:
        res = requests.post(url, json=payload, timeout=10).json()
        if "result" in res:
            return res["result"]["value"] / 10**9 # SOL tiene 9 decimales (Lamports)
    except Exception:
        pass
    return 0.0

def get_sol_tokens(address):
    """Busca USDC y otros tokens populares en Solana."""
    url = "https://api.mainnet-beta.solana.com"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            address,
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed"}
        ]
    }
    tokens = {}
    try:
        res = requests.post(url, json=payload, timeout=10).json()
        if "result" in res:
            for item in res["result"]["value"]:
                info = item["account"]["data"]["parsed"]["info"]
                mint = info["mint"]
                amount = info["tokenAmount"]["uiAmount"]
                # USDC Mint: EPjFW38kbWJ4PLndcxeTMaEe3RZ5bRPyAXqree7dnE3
                if mint == "EPjFW38kbWJ4PLndcxeTMaEe3RZ5bRPyAXqree7dnE3":
                    tokens["USDC-SOL"] = amount
                elif amount > 0:
                    tokens[f"Token-{mint[:4]}"] = amount
    except Exception:
        pass
    return tokens

def get_sol_last_move(address):
    url = "https://api.mainnet-beta.solana.com"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [address, {"limit": 1}]
    }
    try:
        res = requests.post(url, json=payload, timeout=10).json()
        if "result" in res and len(res["result"]) > 0:
            ts = res["result"][0].get("blockTime")
            if ts:
                return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(ts))
    except Exception:
        pass
    return "Sin movimientos"

def main():
    global wallets_scanned
    logging.info(f"Escaneo Solana iniciado (Batch: {BATCH_SIZE})...")
    try:
        while True:
            batch = {}
            for _ in range(BATCH_SIZE):
                seed = Bip39MnemonicGenerator().FromWordsNumber(Bip39WordsNum.WORDS_NUM_12)
                addr = generate_sol_wallet(seed)
                batch[addr] = seed

            with open(log_file_path, "a", buffering=1) as log_f:
                for addr, seed in batch.items():
                    # 1. Consultar balance base SOL (Mínimo necesario)
                    sol_bal = get_sol_balance(addr)
                    usdc_sol = 0.0
                    last_move = "Sin movimientos"
                    
                    # SOLO profundizar si hay SOL o actividad potencial
                    if sol_bal > 0:
                        # 2. Consultar Tokens (USDC)
                        tokens = get_sol_tokens(addr)
                        usdc_sol = tokens.get("USDC-SOL", 0.0)
                        time.sleep(0.2)

                        # 3. Obtener último movimiento
                        last_move = get_sol_last_move(addr)
                        time.sleep(0.2)
                    
                    # Registro en log
                    log_f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - INFO - Scan: {addr} | SOL: {sol_bal:.6f} | USDC: {usdc_sol:.6f} | Mov: {last_move} | Seed: {seed}\n")
                    log_f.flush()

                    if sol_bal > 0 or usdc_sol > 0:
                        print(f"\n[!] ¡HALLAZGO SOLANA!: {addr} | SOL: {sol_bal:.6f} | USDC: {usdc_sol:.6f} | Mov: {last_move} | Seed: {seed}")
                        with open(wallets_file_path, "a") as f:
                            f.write(f"Seed: {seed}\nAddress: {addr}\nSOL: {sol_bal:.6f} | USDC: {usdc_sol:.6f}\nMovimiento: {last_move}\n\n")
                            f.flush()
                    else:
                        # Pequeño delay para no saturar el RPC público en el loop rápido
                        time.sleep(0.05)

            wallets_scanned += BATCH_SIZE
            update_cmd_title()
            print(f"\rSOL Wallets escaneadas: {wallets_scanned}", end="", flush=True)
            time.sleep(DELAY_BETWEEN_BATCHES)

    except KeyboardInterrupt:
        print("\n")
        logging.info("Escaneo Solana detenido.")

if __name__ == "__main__":
    main()
