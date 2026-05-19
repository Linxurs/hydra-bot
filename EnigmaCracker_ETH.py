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
LOG_FILE_NAME = "enigmacracker_eth.log"
ENV_FILE_NAME = "EnigmaCracker.env"
WALLETS_FILE_NAME = "eth_wallets_with_balance.txt"
BATCH_SIZE = 20            # Etherscan permite hasta 20 direcciones por consulta multi-balance
DELAY_BETWEEN_BATCHES = 2  # Etherscan free permite 5 req/seg

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
ETHERSCAN_KEY = os.getenv("ETHERSCAN_API_KEY")

def update_cmd_title():
    if platform.system() == "Windows":
        os.system(f"title EnigmaCracker_ETH.py - Wallets Scanned: {wallets_scanned}")

def generate_eth_wallet(seed):
    seed_bytes = Bip39SeedGenerator(seed).Generate()
    bip44_acc_ctx = (
        Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM)
        .Purpose()
        .Coin()
        .Account(0)
        .Change(Bip44Changes.CHAIN_EXT)
        .AddressIndex(0)
    )
    return bip44_acc_ctx.PublicKey().ToAddress()

def get_eth_balances(addresses):
    addr_str = ",".join(addresses)
    url = f"https://api.etherscan.io/api?module=account&action=balancemulti&address={addr_str}&tag=latest&apikey={ETHERSCAN_KEY}"
    try:
        res = requests.get(url, timeout=20).json()
        if res["status"] == "1":
            return {item["account"]: int(item["balance"]) / 10**18 for item in res["result"]}
    except Exception as e:
        logging.error(f"Error consultando ETH: {e}")
    return {}

# Contratos de Tokens (ERC-20)
TOKENS = {
    "USDT": ("0xdAC17F958D2ee523a2206206994597C13D831ec7", 6),
    "USDC": ("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eb48", 6),
    "DAI":  ("0x6B175474E89094C44Da98b954EedeAC495271d0F", 18),
}

def get_token_balance(address, contract_address, decimals):
    url = f"https://api.etherscan.io/api?module=account&action=tokenbalance&contractaddress={contract_address}&address={address}&tag=latest&apikey={ETHERSCAN_KEY}"
    try:
        res = requests.get(url, timeout=20).json()
        if res["status"] == "1":
            return int(res["result"]) / 10**decimals
    except Exception:
        pass
    return 0.0

def get_eth_last_move(address):
    url = f"https://api.etherscan.io/api?module=account&action=txlist&address={address}&startblock=0&endblock=99999999&page=1&offset=1&sort=desc&apikey={ETHERSCAN_KEY}"
    try:
        res = requests.get(url, timeout=20).json()
        if res["status"] == "1" and len(res["result"]) > 0:
            ts = int(res["result"][0]["timeStamp"])
            return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(ts))
    except Exception:
        pass
    return "Sin movimientos"

def main():
    global wallets_scanned
    if not ETHERSCAN_KEY:
        logging.error("No se encontró ETHERSCAN_API_KEY en el .env")
        return

    logging.info(f"Escaneo Multimoneda iniciado (Batch: {BATCH_SIZE})...")
    try:
        while True:
            batch = {}
            for _ in range(BATCH_SIZE):
                seed = Bip39MnemonicGenerator().FromWordsNumber(Bip39WordsNum.WORDS_NUM_12)
                addr = generate_eth_wallet(seed)
                batch[addr] = seed

            # 1. Consultar ETH (Batch)
            eth_results = get_eth_balances(list(batch.keys()))

            with open(log_file_path, "a", buffering=1) as log_f:
                for addr, seed in batch.items():
                    eth_bal = eth_results.get(addr, 0.0)
                    token_balances = {"USDT": 0.0, "USDC": 0.0, "DAI": 0.0}
                    last_move = "Sin movimientos"
                    found_token = False

                    # SOLO profundizar si hay ETH o si queremos ser exhaustivos (pero con cautela)
                    # Para optimizar, si el balance es 0, no consultamos tokens ni movimientos a menos que sea necesario.
                    if eth_bal > 0:
                        # 2. Consultar Tokens (USDT, USDC, DAI)
                        for name, (contract, decimals) in TOKENS.items():
                            bal = get_token_balance(addr, contract, decimals)
                            token_balances[name] = bal
                            if bal > 0.000001: found_token = True
                            time.sleep(0.25) # Respetar rate limit

                        # 3. Obtener último movimiento
                        last_move = get_eth_last_move(addr)
                        time.sleep(0.25)

                    # Registro organizado en el log
                    token_str = " | ".join([f"{n}: {b:.2f}" for n, b in token_balances.items()])
                    log_f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - INFO - Scan: {addr} | ETH: {eth_bal:.6f} | {token_str} | Mov: {last_move} | Seed: {seed}\n")
                    log_f.flush()

                    if eth_bal > 0 or found_token:
                        res_str = f"ETH: {eth_bal:.6f} | " + " | ".join([f"{n}: {b:.6f}" for n, b in token_balances.items()])
                        print(f"\n[!] ¡HALLAZGO!: {addr} | {res_str} | Mov: {last_move} | Seed: {seed}")
                        with open(wallets_file_path, "a") as f:
                            f.write(f"Seed: {seed}\nAddress: {addr}\n{res_str}\nMovimiento: {last_move}\n\n")
                            f.flush()

            wallets_scanned += BATCH_SIZE
            update_cmd_title()
            print(f"\rETH Wallets escaneadas: {wallets_scanned}", end="", flush=True)
            time.sleep(DELAY_BETWEEN_BATCHES)

    except KeyboardInterrupt:
        print("\n")
        logging.info("Escaneo ETH detenido.")

if __name__ == "__main__":
    main()
