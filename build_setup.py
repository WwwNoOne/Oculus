import os
import subprocess
import sys
from pathlib import Path

def build():
    print("[*] Iniciando compilación de Oculus Desktop App...")
    
    # Asegurar que pyinstaller está instalado
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    base_dir = Path(__file__).parent.resolve()
    main_script = base_dir / "main.py"
    src_dir = base_dir / "src"
    
    # Comando PyInstaller
    # --windowed oculta la consola negra de Windows
    # --onedir crea una carpeta optimizada con el .exe adentro
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "Oculus_DTE_Manager",
        f"--add-data={src_dir};src/",
        str(main_script)
    ]
    
    subprocess.run(cmd, cwd=str(base_dir))
    
    print("[*] Compilación terminada.")
    print("[*] Puedes encontrar el ejecutable en la carpeta: dist/Oculus_DTE_Manager/")
    print("[*] Para crear un 'setup.exe' instalador, puedes comprimir esta carpeta usando Inno Setup.")

if __name__ == "__main__":
    build()
