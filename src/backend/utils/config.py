import os
import sys
from pathlib import Path

def get_data_dir() -> Path:
    """
    Retorna la ruta donde se guardará la base de datos y los PDFs.
    Si estamos en producción (.exe), usa Documentos para evitar pérdida de datos.
    Si estamos desarrollando, usa la carpeta local.

    La variable de entorno OCULUS_DATA_DIR permite apuntar a un workspace
    aislado (p. ej. pruebas con PRUEBAS/salida sin tocar los datos reales).
    """
    override = os.environ.get("OCULUS_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if getattr(sys, 'frozen', False):
        # Producción: C:\Users\Usuario\Documents\Oculus_Workspace
        return Path.home() / "Documents" / "Oculus_Workspace"
    else:
        # Desarrollo: Carpeta del proyecto
        return Path(__file__).resolve().parent.parent.parent.parent / "data"

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
SRC_DIR = BASE_DIR / "src"
FRONTEND_DIR = SRC_DIR / "frontend"
BACKEND_DIR = SRC_DIR / "backend"

# Carpetas de datos (Aisladas del código fuente)
DATA_DIR = get_data_dir()
CARPETA_DESCARGAS = DATA_DIR / "01_Descargas"
CARPETA_PROCESADOS = DATA_DIR / "02_Procesados"
CARPETA_OTROS_DTES = DATA_DIR / "03_Otros_DTEs"
CARPETA_REVISION = DATA_DIR / "04_Revision_Manual"
CARPETA_ADJUNTOS_OTROS = DATA_DIR / "06_Adjuntos_Otros"
CARPETA_DUPLICADOS = DATA_DIR / "08_Duplicados"
CARPETA_ERRORES = DATA_DIR / "09_Errores"
CARPETA_BD = DATA_DIR / "db"
CARPETA_LOGS = DATA_DIR / "logs"

# Asegurar que las carpetas existan
def init_directories():
    directories = [
        DATA_DIR, CARPETA_DESCARGAS, CARPETA_PROCESADOS, 
        CARPETA_OTROS_DTES, CARPETA_REVISION,
        CARPETA_ADJUNTOS_OTROS,
        CARPETA_DUPLICADOS,
        CARPETA_ERRORES,
        CARPETA_BD, CARPETA_LOGS
    ]
    for d in directories:
        d.mkdir(parents=True, exist_ok=True)

init_directories()

DB_PATH = CARPETA_BD / "oculus.db"
