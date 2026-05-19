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

# Constants
LOG_FILE_NAME = "enigmacracker.log"
ENV_FILE_NAME = "EnigmaCracker.env"
WALLETS_FILE_NAME = "wallets_with_balance.txt"
BATCH_SIZE = 60            # Wallets por cada petición
DELAY_BETWEEN_BATCHES = 11 # Segundos entre peticiones (API Limit: 1req/10s)

# Global counter
wallets_scanned = 0

# Paths
directory = os.path.dirname(os.path.abspath(__file__))
log_file_path = os.path.join(directory, LOG_FILE_NAME)
env_file_path = os.path.join(directory, ENV_FILE_NAME)
wallets_file_path = os.path.join(directory, WALLETS_FILE_NAME)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler(sys.stdout),
    ],
)

# Silence standard requests logging to keep it silent
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

load_dotenv(env_file_path)

def update_cmd_title():
    if platform.system() == "Windows":
        os.system(f"title EnigmaCracker.py - Wallets Scanned: {wallets_scanned}")

def generate_bip39_mnemonic():
    return Bip39MnemonicGenerator().FromWordsNumber(Bip39WordsNum.WORDS_NUM_12)

def generate_wallet_from_seed(seed):
    seed_bytes = Bip39SeedGenerator(seed).Generate()
    bip44_acc_ctx = (
        Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN)
        .Purpose()
        .Coin()
        .Account(0)
        .Change(Bip44Changes.CHAIN_EXT)
        .AddressIndex(0)
    )
    return bip44_acc_ctx.PublicKey().ToAddress()

def check_btc_multi(address_map):
    addresses = "|".join(address_map.keys())
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(
            f"https://blockchain.info/multiaddr?active={addresses}",
            headers=headers,
            timeout=30
        )
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:
            logging.warning("(!) Rate Limit alcanzado. Pausando 30s...")
            time.sleep(30)
            return "LIMIT"
    except Exception as e:
        logging.error(f"(!) Error de conexión: {e}")
    return None

def write_wallet_to_file(seed, BTC_address, BTC_balance, last_move):
    with open(wallets_file_path, "a") as f:
        log_message = (
            f"Seed: {seed}\n"
            f"BTC Address: {BTC_address}\n"
            f"BTC Balance: {BTC_balance} BTC\n"
            f"Último Movimiento: {last_move}\n\n"
        )
        f.write(log_message)

def main():
    global wallets_scanned
    logging.info(f"Escaneo iniciado (Batch: {BATCH_SIZE} cada {DELAY_BETWEEN_BATCHES}s)")
    try:
        while True:
            # 1. Generar lote en memoria
            batch = {}
            for _ in range(BATCH_SIZE):
                seed = generate_bip39_mnemonic()
                addr = generate_wallet_from_seed(seed)
                batch[addr] = seed

            # 2. Consultar lote
            data = check_btc_multi(batch)
            
            if data and data != "LIMIT" and "addresses" in data:
                # Mapear transacciones
                txs_by_addr = {}
                if "txs" in data:
                    for tx in data["txs"]:
                        for input_out in tx.get("inputs", []) + tx.get("out", []):
                            addr = input_out.get("prev_out", {}).get("addr") or input_out.get("addr")
                            if addr in batch:
                                if addr not in txs_by_addr or tx["time"] > txs_by_addr[addr]:
                                    txs_by_addr[addr] = tx["time"]

                # 3. Registrar resultados organizados
                with open(log_file_path, "a") as log_f:
                    for addr_info in data["addresses"]:
                        addr = addr_info["address"]
                        bal_satoshi = addr_info["final_balance"]
                        btc = bal_satoshi / 100000000
                        seed = batch[addr]
                        
                        last_move_ts = txs_by_addr.get(addr)
                        last_move_str = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(last_move_ts)) if last_move_ts else "Sin movimientos"

                        # Registro DIRECTO en el archivo para evitar la consola
                        log_f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - INFO - Scan: {addr} | Balance: {btc:.8f} BTC | Mov: {last_move_str} | Seed: {seed}\n")

                        if bal_satoshi > 0:
                            print(f"\n[!] ¡WALLET ENCONTRADA!: {addr} -> {btc:.8f} BTC | Movimiento: {last_move_str}")
                            write_wallet_to_file(seed, addr, f"{btc:.8f}", last_move_str)

                wallets_scanned += BATCH_SIZE
                update_cmd_title()
                print(f"\rWallets escaneadas: {wallets_scanned}", end="", flush=True)
            
            time.sleep(DELAY_BETWEEN_BATCHES)

    except KeyboardInterrupt:
        print("\n")
        logging.info("Escaneo detenido por el usuario.")

if __name__ == "__main__":
    main()
