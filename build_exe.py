import os
import shutil
import subprocess
from pathlib import Path

# Configuración
PROJECT_DIR = Path(__file__).resolve().parent
MAIN_SCRIPT = PROJECT_DIR / "main.py"
SRC_FRONTEND = PROJECT_DIR / "src" / "frontend"
DIST_DIR = PROJECT_DIR / "dist"
BUILD_DIR = PROJECT_DIR / "build"

def clean_build():
    print("Limpiando directorios de build anteriores...")
    if DIST_DIR.exists(): shutil.rmtree(DIST_DIR)
    if BUILD_DIR.exists(): shutil.rmtree(BUILD_DIR)
    spec_file = PROJECT_DIR / "Oculus.spec"
    if spec_file.exists(): spec_file.unlink()

def build_exe():
    print("Generando ejecutable con PyInstaller...")
    
    # Construir el comando. 
    # Usamos --noconsole para ocultar la terminal (Windowed)
    # --add-data para incluir los archivos estáticos HTML/JS/CSS
    
    separator = ";" # En windows es ';' en Linux/Mac es ':'
    frontend_data = f"{SRC_FRONTEND}{separator}src/frontend"
    
    cmd = [
        ".venv\\Scripts\\pyinstaller",
        "--name=Oculus",
        "--windowed",
        "--contents-directory=internal",
        "--icon=icono.ico", # Usar el icono que convertimos
        f"--add-data={frontend_data}",
        "--clean",
        str(MAIN_SCRIPT)
    ]
    
    subprocess.run(cmd, check=True)
    print("\n¡Ejecutable generado exitosamente en la carpeta 'dist/Oculus'!")

if __name__ == "__main__":
    clean_build()
    build_exe()
