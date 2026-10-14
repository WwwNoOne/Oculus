import webview
import sys
import os
from pathlib import Path

# Agregar ruta base para importaciones relativas
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Monkeypatch para bug de Python 3.14 con WMI en Windows que causa fallos al importar librerías de IA
import platform
_original_win32_ver = platform.win32_ver
def _patched_win32_ver(*args, **kwargs):
    try:
        return _original_win32_ver(*args, **kwargs)
    except AttributeError:
        return ('10', '10.0.0', '', 'Multiprocessor Free')
platform.win32_ver = _patched_win32_ver

from src.backend.utils.config import FRONTEND_DIR, CARPETA_LOGS
from src.backend.api import Api

class LoggerWriter:
    def __init__(self, filepath):
        self.filepath = filepath
        self.terminal = sys.stdout
        
    def write(self, message):
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(message)
            
    def flush(self):
        pass

def main():
    # Setup global logging
    log_file = CARPETA_LOGS / "app.log"
    sys.stdout = LoggerWriter(log_file)
    sys.stderr = LoggerWriter(log_file)
    
    print("\\n\\n==========================================")
    print("Iniciando Oculus Gestor DTE")
    print("==========================================")

    api = Api()
    index_html = FRONTEND_DIR / "index.html"
    
    # Crear la ventana de la aplicación de escritorio
    window = webview.create_window(
        'Oculus - Gestor de DTEs',
        url=str(index_html),
        js_api=api,
        width=1100,
        height=800,
        min_size=(900, 600),
        background_color='#121212' # Dark mode background
    )
    
    # Iniciar la aplicación
    # debug=False evita que se abra la consola web de inspección
    webview.start(debug=False)

if __name__ == '__main__':
    main()
