import os
import json
import fitz  # PyMuPDF
from pathlib import Path

def test_extraction():
    # Rutas
    base_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    test_dir = base_dir / "datos de prueba" / "prueba"
    
    if not test_dir.exists():
        print(f"Error: La carpeta {test_dir} no existe.")
        return

    # Carpeta para resultados
    out_dir = test_dir / "text_results"
    out_dir.mkdir(exist_ok=True)

    print(f"Iniciando extracción local en: {test_dir}")
    print("-" * 50)
    
    files = list(test_dir.glob("*.*"))
    pdf_files = [f for f in files if f.suffix.lower() == '.pdf']
    json_files = [f for f in files if f.suffix.lower() == '.json']
    
    # Procesar PDFs
    print(f"Archivos PDF encontrados: {len(pdf_files)}")
    for pdf_file in pdf_files:
        try:
            doc = fitz.open(pdf_file)
            texto_completo = ""
            for page in doc:
                texto_completo += page.get_text() + "\n"
            
            # Limpiar texto un poco
            texto_limpio = texto_completo.strip()
            
            out_file = out_dir / f"{pdf_file.stem}.txt"
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(texto_limpio)
                
            estado = "OK" if len(texto_limpio) > 50 else "VACÍO (Posible imagen escaneada)"
            print(f"[PDF] {pdf_file.name} -> {estado} ({len(texto_limpio)} caracteres)")
            
        except Exception as e:
            print(f"[ERROR] PDF {pdf_file.name}: {e}")

    # Procesar JSONs
    print(f"\nArchivos JSON encontrados: {len(json_files)}")
    for json_file in json_files:
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            texto = json.dumps(data, indent=2, ensure_ascii=False)
            
            out_file = out_dir / f"{json_file.stem}_json.txt"
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(texto)
                
            print(f"[JSON] {json_file.name} -> Extraído ({len(texto)} caracteres)")
        except Exception as e:
            print(f"[ERROR] JSON {json_file.name}: {e}")

    print("-" * 50)
    print(f"Extracción finalizada. Revisa la carpeta: {out_dir}")

if __name__ == "__main__":
    test_extraction()
