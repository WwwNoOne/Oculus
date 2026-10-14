"""Prueba el pipeline con PRUEBAS/01_Descargas en un workspace aislado.

Uso:
    .\\.venv\\Scripts\\python.exe probar_pipeline.py [--solo N]

- NO toca data/ real: trabaja en PRUEBAS/salida (se recrea en cada corrida,
  incluyendo su propia base de datos).
- PRUEBAS/01_Descargas solo se lee: se copia a un staging temporal porque
  el pipeline mueve los archivos al procesarlos.
- Sin claves de IA configuradas no hay gasto: los JSON se estandarizan en
  local y los PDF sin pareja usan el fallback local.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PRUEBAS = BASE / "PRUEBAS"
FUENTE = PRUEBAS / "01_Descargas"
SALIDA = PRUEBAS / "salida"

# El workspace aislado debe definirse ANTES de importar src.backend (las
# constantes de config se resuelven en tiempo de importacion).
os.environ["OCULUS_DATA_DIR"] = str(SALIDA)
sys.path.insert(0, str(BASE))


def _contar(carpeta: Path, patron: str) -> int:
    if not carpeta.exists():
        return 0
    return sum(1 for p in carpeta.rglob(patron) if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description="Prueba el pipeline con datos de PRUEBAS.")
    parser.add_argument("--solo", type=int, default=0, help="Procesar solo los primeros N archivos.")
    args = parser.parse_args()

    if not FUENTE.exists():
        print(f"[!] No existe la carpeta de pruebas: {FUENTE}")
        return 1
    archivos = sorted(
        p for p in FUENTE.glob("*.*")
        if p.suffix.lower() in {".pdf", ".json"} and not p.name.lower().endswith("_estado.json")
    )
    if not archivos:
        print("[!] PRUEBAS/01_Descargas no contiene PDF ni JSON.")
        return 1
    if args.solo > 0:
        archivos = archivos[:args.solo]

    if SALIDA.exists():
        # Reintentos: OneDrive/antivirus pueden bloquear archivos momentaneamente.
        import time

        time.sleep(10)
        for intento in range(6):
            try:
                shutil.rmtree(SALIDA)
                break
            except OSError:
                if intento == 5:
                    raise
                time.sleep(5)
    staging = SALIDA / "entrada_prueba"
    staging.mkdir(parents=True, exist_ok=True)
    for origen in archivos:
        shutil.copy2(str(origen), str(staging / origen.name))
    print(f"[*] Fixture: {len(archivos)} archivos copiados a {staging}")

    from src.backend.services.dte_service import DTEService

    servicio = DTEService()
    resultados = servicio.process_downloads(source_dir=staging)
    print(f"[*] Resultados: {resultados}")

    restantes = sum(1 for p in staging.iterdir() if p.is_file())
    print(f"[*] Archivos sin procesar en staging: {restantes}")

    filas = [
        ("02_Procesados (PDF)", SALIDA / "02_Procesados", "*.pdf"),
        ("03_Otros_DTEs (PDF)", SALIDA / "03_Otros_DTEs", "*.pdf"),
        ("08_Duplicados (todos)", SALIDA / "08_Duplicados", "*.*"),
        ("09_Errores (todos)", SALIDA / "09_Errores", "*.*"),
    ]
    print("\nDestino                          Archivos")
    print("-" * 50)
    for nombre, carpeta, patron in filas:
        print(f"{nombre:32} { _contar(carpeta, patron)}")
    print(f"\nWorkspace aislado en: {SALIDA} (BD incluida, datos reales intactos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
