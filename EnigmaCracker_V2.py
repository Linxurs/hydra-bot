import logging
import os
import platform
import sys
import time
import multiprocessing
from bip_utils import (
    Bip39MnemonicGenerator,
    Bip39SeedGenerator,
    Bip39WordsNum,
    Bip44,
    Bip44Changes,
    Bip44Coins,
)
from hydra_local_engine import LocalSearchEngine

# Configuración
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
BTC_DB_PATH = os.path.join(DATA_DIR, "btc_balances.txt")
FOUND_FILE = os.path.join(DATA_DIR, "FOUND_WALLETS.txt")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(processName)s] - %(message)s",
    handlers=[
        logging.FileHandler("enigmacracker_v2.log"),
        logging.StreamHandler(sys.stdout),
    ],
)

def generate_and_check(engine, stats_queue):
    """Función que ejecuta cada proceso hijo."""
    generator = Bip39MnemonicGenerator()
    local_count = 0
    start_time = time.time()

    while True:
        # Generar
        mnemonic = generator.FromWordsNumber(Bip39WordsNum.WORDS_NUM_12)
        seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
        
        # Derivar BTC Address
        address = (
            Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN)
            .Purpose()
            .Coin()
            .Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(0)
            .PublicKey()
            .ToAddress()
        )

        # Buscar Localmente
        if engine.contains(address):
            logging.info(f"!!! WALLET ENCONTRADA !!!: {address} | Seed: {mnemonic}")
            with open(FOUND_FILE, "a") as f:
                f.write(f"Address: {address} | Seed: {mnemonic}\n")

        local_count += 1
        
        # Reportar stats cada 1000 intentos para no saturar la cola
        if local_count >= 1000:
            stats_queue.put(local_count)
            local_count = 0

def main():
    print("--- EnigmaCracker V2 (Local Turbo) ---")
    if not os.path.exists(BTC_DB_PATH) or os.path.getsize(BTC_DB_PATH) == 0:
        print(f"ERROR: No se encuentra el archivo {BTC_DB_PATH}")
        print("Debes descargar un UTXO dump y guardarlo en esa ruta.")
        return

    num_cores = multiprocessing.cpu_count()
    print(f"Detectados {num_cores} núcleos. Iniciando motores...")

    engine = LocalSearchEngine(BTC_DB_PATH)
    stats_queue = multiprocessing.Queue()
    
    processes = []
    for i in range(num_cores):
        p = multiprocessing.Process(
            target=generate_and_check, 
            args=(engine, stats_queue),
            name=f"Worker-{i}"
        )
        p.start()
        processes.append(p)

    total_scanned = 0
    start_time = time.time()

    try:
        while True:
            while not stats_queue.empty():
                total_scanned += stats_queue.get()
            
            elapsed = time.time() - start_time
            speed = total_scanned / elapsed if elapsed > 0 else 0
            
            sys.stdout.write(f"\rScanned: {total_scanned:,} | Velocidad: {speed:,.2f} seeds/seg")
            sys.stdout.flush()
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nDeteniendo procesos...")
        for p in processes:
            p.terminate()
        print("Escaneo finalizado.")

if __name__ == "__main__":
    main()
