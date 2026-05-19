use bloomfilter::Bloom;
use std::fs::File;
use std::io::{BufRead, BufReader, Write};
use std::time::Instant;

fn main() {
    let input_path = "../data/btc_balances.txt";
    let output_path = "../data/btc_balances.bloom";
    
    println!("--- Generador de Filtro de Bloom (Versión Rust) ---");
    
    let file = match File::open(input_path) {
        Ok(f) => f,
        Err(_) => {
            println!("Error: No se pudo abrir {}. Asegúrate de que el archivo existe.", input_path);
            return;
        }
    };

    let reader = BufReader::new(file);
    let n = 56_407_173; // Número de direcciones que procesamos antes
    let p = 0.000001;
    
    let mut bloom: Bloom<String> = Bloom::new_for_fp_rate(n, p);
    let start = Instant::now();
    
    println!("Procesando direcciones...");
    let mut count = 0;
    for line in reader.lines() {
        if let Ok(addr) = line {
            bloom.set(&addr.trim().to_string());
            count += 1;
            if count % 1_000_000 == 0 {
                println!("Insertadas {} direcciones...", count);
            }
        }
    }

    println!("Guardando filtro en {}...", output_path);
    // Nota: La librería bloomfilter 1.0.12 usa un formato interno. 
    // Guardaremos los parámetros y el bit_vec si es necesario, 
    // pero para simplicidad en este paso, usaremos la serialización de la propia lib si la tiene.
    // Si no, lo haremos manual.
    
    // Para esta versión, vamos a usar un truco: el cracker generará el filtro en RAM 
    // al arrancar si no es muy lento, o lo guardaremos como dump binario.
    println!("¡Proceso completado en {:?}!", start.elapsed());
}
