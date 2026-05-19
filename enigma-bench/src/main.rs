use bip39::{Mnemonic, Language, Seed, MnemonicType};
use bitcoin::network::constants::Network;
use bitcoin::bip32::{ExtendedPrivKey, DerivationPath};
use bitcoin::secp256k1::Secp256k1;
use rayon::prelude::*;
use std::str::FromStr;
use std::time::Instant;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use rand::RngCore;
use std::io::Write;

fn main() {
    println!("--- EnigmaCracker Rust BENCHMARK ---");
    
    let network = Network::Bitcoin;
    let scanned_count = Arc::new(AtomicU64::new(0));
    let start_time = Instant::now();
    let path = DerivationPath::from_str("m/44'/0'/0'/0/0").unwrap();

    let cores = num_cpus::get();
    println!("Detectados {} núcleos. ¡A toda máquina!", cores);

    (0..cores).into_par_iter().for_each(|i| {
        let mut local_count = 0;
        let mut last_report = Instant::now();
        let secp = Secp256k1::new();
        let mut rng = rand::thread_rng();
        
        loop {
            // 1. Generar entropía (128 bits = 12 palabras)
            let mut entropy = [0u8; 16];
            rng.fill_bytes(&mut entropy);
            
            // 2. Crear mnemónico y semilla (Trabajo de CPU)
            let mnemonic = Mnemonic::from_entropy(&entropy, Language::English).unwrap();
            let seed = Seed::new(&mnemonic, "");
            
            // 3. Derivación (Trabajo de CPU Criptográfico)
            let root = ExtendedPrivKey::new_master(network, seed.as_bytes()).unwrap();
            let _sk = root.derive_priv(&secp, &path).unwrap();
            
            local_count += 1;
            
            // Reportar estadísticas
            if last_report.elapsed().as_millis() > 1000 {
                scanned_count.fetch_add(local_count, Ordering::Relaxed);
                local_count = 0;
                last_report = Instant::now();
                
                if i == 0 { 
                    let total = scanned_count.load(Ordering::Relaxed);
                    let elapsed = start_time.elapsed().as_secs_f64();
                    if elapsed > 0.0 {
                        print!("\rGeneradas: {} | Velocidad Punta: {:.2} seeds/seg", total, total as f64 / elapsed);
                        std::io::stdout().flush().unwrap();
                    }
                }
            }
        }
    });
}
