use bip39::{Mnemonic, Language, Seed};
use bitcoin::network::constants::Network;
use bitcoin::Address;
use bitcoin::PublicKey;
use bitcoin::secp256k1::Secp256k1;
use bitcoin::bip32::{ExtendedPrivKey, DerivationPath};
use rayon::prelude::*;
use std::str::FromStr;
use std::time::Instant;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use rand::RngCore;
use bloomfilter::Bloom;
use std::fs::OpenOptions;
use std::io::Write;
use bitcoin::hashes::Hash;

fn main() {
    println!("--- EnigmaCracker Rust Edition (Turbo + Bloom) ---");
    
    let txt_path = "../data/btc_balances.txt";
    let found_path = "../data/FOUND_RUST.txt";

    if !std::path::Path::new(txt_path).exists() {
        println!("ERROR: No se encuentra {}.", txt_path);
        return;
    }

    println!("Construyendo Filtro de Bloom (Binario) en RAM...");
    let start_bloom = Instant::now();
    
    // El filtro ahora guardará hashes de 20 bytes (Hash160)
    let mut bloom: Bloom<bitcoin::hashes::hash160::Hash> = Bloom::new_for_fp_rate(56_407_173, 0.000001);
    
    let file = std::fs::File::open(txt_path).unwrap();
    let reader = std::io::BufReader::new(file);
    
    let mut count = 0;
    for line in std::io::BufRead::lines(reader) {
        if let Ok(addr_str) = line {
            if let Ok(addr) = Address::from_str(addr_str.trim()).map(|a| a.assume_checked()) {
                match addr.payload {
                    bitcoin::address::Payload::PubkeyHash(hash) => {
                        bloom.set(&hash);
                        count += 1;
                    },
                    _ => {}
                }
            }
            if count % 10_000_000 == 0 {
                println!("  > Indexadas {} direcciones...", count);
            }
        }
    }
    println!("¡Filtro listo en RAM! ({} direcciones en {:?})", count, start_bloom.elapsed());
    
    let network = Network::Bitcoin;
    let scanned_count = Arc::new(AtomicU64::new(0));
    let start_time = Instant::now();
    let path = DerivationPath::from_str("m/44'/0'/0'/0/0").unwrap();

    let cores = num_cpus::get();
    println!("Motores listos en {} núcleos.", cores);

    (0..cores).into_par_iter().for_each(|i| {
        let mut local_count = 0;
        let mut last_report = Instant::now();
        let secp = Secp256k1::new();
        let mut rng = rand::thread_rng();
        
        loop {
            let mut entropy = [0u8; 16];
            rng.fill_bytes(&mut entropy);
            
            let mnemonic = Mnemonic::from_entropy(&entropy, Language::English).unwrap();
            let seed = Seed::new(&mnemonic, "");
            
            let root = ExtendedPrivKey::new_master(network, seed.as_bytes()).unwrap();
            let sk = root.derive_priv(&secp, &path).unwrap();
            
            // OPTIMIZACIÓN EXTREMA: Hash160 directo sin strings
            let pk_bytes = sk.private_key.public_key(&secp).serialize();
            let hash160 = bitcoin::hashes::hash160::Hash::hash(&pk_bytes);

            if bloom.check(&hash160) {
                let address = Address::p2pkh(&PublicKey::new(sk.private_key.public_key(&secp)), network).to_string();
                let result = format!("Address: {} | Seed: {}\n", address, mnemonic.phrase());
                println!("\n[!!!] POSIBLE HALLAZGO: {}", result);
                
                if let Ok(mut file) = OpenOptions::new().append(true).create(true).open(found_path) {
                    let _ = writeln!(file, "{}", result);
                }
            }

            local_count += 1;
            
            if last_report.elapsed().as_millis() > 1000 {
                scanned_count.fetch_add(local_count, Ordering::Relaxed);
                local_count = 0;
                last_report = Instant::now();
                
                if i == 0 { 
                    let total = scanned_count.load(Ordering::Relaxed);
                    let elapsed = start_time.elapsed().as_secs_f64();
                    if elapsed > 0.0 {
                        print!("\rSeeds: {} | Velocidad: {:.2} seeds/seg", total, total as f64 / elapsed);
                        std::io::stdout().flush().unwrap();
                    }
                }
            }
        }
    });
}
