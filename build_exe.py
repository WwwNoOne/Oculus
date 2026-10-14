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
# Fuera de OneDrive: el sync bloquea los borrados durante el build.
OUT_BASE = Path(os.environ.get("TEMP", r"C:\Temp")) / "oculus_build"
OUT_DIST = OUT_BASE / "dist"
OUT_WORK = OUT_BASE / "work"

def _rmtree_resiliente(ruta: Path):
    import time
    for _ in range(6):
        try:
            if ruta.exists():
                shutil.rmtree(ruta)
            return
        except OSError:
            # OneDrive/antivirus pueden bloquear momentaneamente.
            time.sleep(5)

def clean_build():
    print("Limpiando directorios de build anteriores...")
    _rmtree_resiliente(OUT_BASE)
    _rmtree_resiliente(DIST_DIR)
    _rmtree_resiliente(BUILD_DIR)
    spec_file = PROJECT_DIR / "OculusV2.spec"
    if spec_file.exists():
        try:
            spec_file.unlink()
        except OSError:
            pass

def build_exe():
    print("Generando ejecutable con PyInstaller...")
    
    # Construir el comando. 
    # Usamos --noconsole para ocultar la terminal (Windowed)
    # --add-data para incluir los archivos estáticos HTML/JS/CSS
    
    separator = ";" # En windows es ';' en Linux/Mac es ':'
    frontend_data = f"{SRC_FRONTEND}{separator}src/frontend"
    
    cmd = [
        ".venv\\Scripts\\pyinstaller",
        "--name=OculusV2",
        "--windowed",
        "--contents-directory=internal",
        "--icon=icono.ico", # Usar el icono que convertimos
        f"--add-data={frontend_data}",
        # Imports dinamicos/opcionales que PyInstaller suele no detectar
        "--hidden-import=keyring.backends.Windows",
        "--hidden-import=msal",
        "--hidden-import=llama_parse",
        "--hidden-import=google_auth_oauthlib.flow",
        "--hidden-import=google.oauth2.credentials",
        "--hidden-import=google.auth.transport.requests",
        "--hidden-import=imap_tools",
        "--hidden-import=email.mime.multipart",
        "--hidden-import=email.mime.application",
        f"--distpath={OUT_DIST}",
        f"--workpath={OUT_WORK}",
        "--clean",
        str(MAIN_SCRIPT)
    ]

    subprocess.run(cmd, check=True)
    final = DIST_DIR / "OculusV2"
    _rmtree_resiliente(final)
    shutil.copytree(OUT_DIST / "OculusV2", final)
    print(f"\n¡Ejecutable generado exitosamente en '{final}'!")

if __name__ == "__main__":
    clean_build()
    build_exe()
