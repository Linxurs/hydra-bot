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
    Cip1852,
    Cip1852Coins,
    Bip44Changes,
    CardanoShelley,
)
from dotenv import load_dotenv

# Configuración
LOG_FILE_NAME = "enigmacracker_ada.log"
ENV_FILE_NAME = "EnigmaCracker.env"
WALLETS_FILE_NAME = "ada_wallets_with_balance.txt"
BATCH_SIZE = 10            # Koios permite consultas por lotes, mantendremos 10 por estabilidad
DELAY_BETWEEN_BATCHES = 2  # Segundos entre lotes

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
        os.system(f"title EnigmaCracker_ADA.py - Wallets Scanned: {wallets_scanned}")

def generate_ada_wallet(seed):
    """Deriva dirección Shelley de Cardano usando Cip1852 y CardanoShelley."""
    seed_bytes = Bip39SeedGenerator(seed).Generate()
    cip1852_acc = (
        Cip1852.FromSeed(seed_bytes, Cip1852Coins.CARDANO_ICARUS)
        .Purpose()
        .Coin()
        .Account(0)
    )
    return CardanoShelley.FromCip1852Object(cip1852_acc).PublicKeys().ToAddress()

def get_ada_balances(addresses):
    """Consulta balances y último movimiento usando Koios API."""
    url = "https://api.koios.rest/api/v1/address_info"
    payload = {"_addresses": addresses}
    results = {}
    try:
        res = requests.post(url, json=payload, timeout=15).json()
        for item in res:
            addr = item["address"]
            bal = int(item.get("total_balance", 0)) / 10**6
            # Buscar último movimiento en la lista de txs si existe
            last_move = "Sin movimientos"
            # Koios no da el tiempo directamente en address_info de forma simple, 
            # pero podemos inferir actividad si total_balance > 0 o tx_count > 0
            if item.get("tx_count", 0) > 0:
                last_move = "Con actividad (ver Explorer)"
            results[addr] = (bal, last_move)
    except Exception as e:
        logging.error(f"Error consultando Koios: {e}")
    return results

def main():
    global wallets_scanned
    logging.info(f"Escaneo Cardano (ADA) iniciado (Batch: {BATCH_SIZE})...")
    try:
        while True:
            batch = {}
            for _ in range(BATCH_SIZE):
                seed = Bip39MnemonicGenerator().FromWordsNumber(Bip39WordsNum.WORDS_NUM_12)
                addr = generate_ada_wallet(seed)
                batch[addr] = seed

            # Consultar saldos y actividad en lote
            ada_results = get_ada_balances(list(batch.keys()))
            
            with open(log_file_path, "a", buffering=1) as log_f:
                for addr, seed in batch.items():
                    res = ada_results.get(addr, (0.0, "Sin movimientos"))
                    ada_bal, last_move = res
                    
                    # Registro forzado en el log
                    log_f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - INFO - Scan: {addr} | ADA: {ada_bal:.6f} | Mov: {last_move} | Seed: {seed}\n")
                    log_f.flush()

                    if ada_bal > 0:
                        print(f"\n[!] ¡HALLAZGO CARDANO!: {addr} | ADA: {ada_bal:.6f} | Mov: {last_move} | Seed: {seed}")
                        with open(wallets_file_path, "a") as f:
                            f.write(f"Seed: {seed}\nAddress: {addr}\nADA: {ada_bal:.6f}\nMovimiento: {last_move}\n\n")
                            f.flush()

            wallets_scanned += BATCH_SIZE
            update_cmd_title()
            print(f"\rADA Wallets escaneadas: {wallets_scanned}", end="", flush=True)
            time.sleep(DELAY_BETWEEN_BATCHES)

    except KeyboardInterrupt:
        print("\n")
        logging.info("Escaneo Cardano detenido.")

if __name__ == "__main__":
    main()
