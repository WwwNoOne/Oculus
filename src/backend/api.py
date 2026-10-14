from src.backend.database.db_manager import db
from src.backend.services.dte_service import DTEService
from src.backend.services.orchestrator import Orchestrator
from src.backend.utils.config import (
    CARPETA_PROCESADOS,
    CARPETA_OTROS_DTES,
    CARPETA_DUPLICADOS,
    CARPETA_ERRORES,
    DATA_DIR,
    DB_PATH,
)

class Api:
    def __init__(self):
        self.dte_service = DTEService()
        self.orchestrator = Orchestrator()
        self.dte_service.migrate_legacy_documents()
    
    def get_stats(self):
        """Obtiene las estadísticas reales de la base de datos"""
        return db.get_stats()

    def get_telemetry(self):
        """Retorna telemetría en vivo del orquestador (progreso real)."""
        return self.orchestrator.get_telemetry()

    def start_processing(self, company_alias=None):
        """Inicia el pipeline de procesamiento real (ahora con el Orquestador).

        company_alias filtra por empresa (client); si coincide con un email,
        filtra por esa cuenta. Vacio o None = todas las cuentas.
        """
        print("Iniciando procesamiento...")
        try:
            self.orchestrator.start(company_alias)
        except Exception as exc:
            return f"No se pudo iniciar el motor: {exc}"
        scope = (company_alias or "").strip()
        if scope:
            return f"Motor iniciado en segundo plano. Alcance: {scope}."
        return "Motor iniciado en segundo plano. Monitoreando todas las cuentas..."

    def stop_processing(self):
        """Solicita una detencion ordenada y espera al final de la operacion actual."""
        self.orchestrator.stop(wait=True)
        return True, "Proceso detenido correctamente."

    def get_clients(self):
        if not CARPETA_PROCESADOS.exists():
            return []
        return sorted(f.name for f in CARPETA_PROCESADOS.iterdir() if f.is_dir())

    def delete_client_data(self, alias, confirm=True, force=False):
        """Limpieza administrativa: elimina las carpetas de trabajo de un alias
        y su registro en companies.

        Reglas de seguridad:
        - confirm debe ser True (confirmacion previa en la UI).
        - Solo alias marcados 'recovery', salvo force=True con doble confirmacion en UI.
        - El alias no puede contener '..', '/' ni '\\' y la ruta resuelta debe
          quedar dentro de DATA_DIR.
        - Nunca toca la BD de cuentas de correo (email_accounts intacta).
        """
        import shutil

        alias = (alias or "").strip()
        if not confirm:
            return False, "Se requiere confirmación explícita para eliminar datos."
        if not alias or alias in {".", ".."} or ".." in alias or "/" in alias or "\\" in alias:
            return False, "Alias inválido."
        kind = db.get_company_kind(alias)
        if kind != "recovery" and not force:
            return False, (
                f"'{alias}' no es un respaldo de recuperación. "
                "Su eliminación requiere autorización explícita (force)."
            )

        data_root = DATA_DIR.resolve()
        targets = [
            CARPETA_PROCESADOS / alias,
            CARPETA_OTROS_DTES / alias,
            DATA_DIR / "05_Respaldo_PDF" / alias,
            CARPETA_DUPLICADOS / alias,
            CARPETA_ERRORES / alias,
        ]
        resolved_targets = []
        for target in targets:
            try:
                resolved = target.resolve()
            except OSError:
                return False, "No se pudo validar la ruta del alias."
            if resolved != data_root and data_root not in resolved.parents:
                return False, "Ruta fuera del área de datos. Operación rechazada."
            resolved_targets.append((target, resolved))

        removed_files = 0
        for target, _resolved in resolved_targets:
            if target.exists():
                removed_files += sum(1 for p in target.rglob("*") if p.is_file())
                shutil.rmtree(target, ignore_errors=False)
        db.remove_company(alias)
        return True, f"Respaldo '{alias}' eliminado: {removed_files} archivos. Esta acción no se puede deshacer."
        
    def get_months(self, client_name):
        meses = set()
        client_path = CARPETA_PROCESADOS / client_name
        if client_path.exists():
            meses.update(f.name for f in client_path.iterdir() if f.is_dir())
        # La BD es la fuente de filas: unir periodos aunque no haya carpeta.
        try:
            meses.update(db.distinct_periods(client_name))
        except Exception:
            pass
        return sorted(meses)
        
    def generate_excel(self, client_name, month_year, save_path):
        from src.backend.services.excel_service import ExcelService
        excel_service = ExcelService()
        client_path = CARPETA_PROCESADOS / client_name
        success, msg, export_path = excel_service.generar_libro_compras(client_path, month_year, save_path)
        # Compatibilidad: callers antiguos esperan (success, msg); los nuevos usan el tercer valor.
        return success, msg, export_path

    def open_folder(self, path):
        """Abre una carpeta de entrega en el explorador del sistema.

        Solo actua sobre directorios existentes. Retorna (success, mensaje).
        """
        import os
        import platform
        import subprocess
        from pathlib import Path

        folder = Path(path) if path else None
        if folder is None or not folder.is_dir():
            return False, "La carpeta de entrega no existe."

        try:
            if platform.system() == "Windows":
                os.startfile(str(folder))
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            return True, f"Abriendo carpeta {folder.name}..."
        except OSError as exc:
            return False, f"No se pudo abrir la carpeta: {exc}"

    def get_excel_diagnostics(self, client_name="", month_year=""):
        """Devuelve rutas y conteos para diagnosticar reportes sin modificar datos."""
        from pathlib import Path

        client_path = CARPETA_PROCESADOS / client_name if client_name else None
        periods = []
        json_count = 0
        pdf_count = 0
        error_count = 0
        selected_path = None

        if client_path and client_path.exists():
            periods = sorted(folder.name for folder in client_path.iterdir() if folder.is_dir())
            if month_year:
                selected_path = client_path / month_year
                if selected_path.exists():
                    # En procesados quedan solo PDF originales; las filas estan en BD.
                    pdf_count = len(list(selected_path.glob("*.pdf")))
                    json_count = db.count_dte_rows(client_name, month_year)
                    # Los fallos lineales viven en 09_Errores/<cliente>/<mes>/.
                    error_backup = CARPETA_ERRORES / client_name / month_year
                    if error_backup.exists():
                        error_count = sum(1 for p in error_backup.rglob("*") if p.is_file())

        return {
            "data_dir": str(DATA_DIR),
            "database": str(DB_PATH),
            "database_exists": DB_PATH.exists(),
            "processed_dir": str(CARPETA_PROCESADOS),
            "client_path": str(client_path) if client_path else None,
            "selected_path": str(selected_path) if selected_path else None,
            "periods": periods,
            "json_count": json_count,
            "pdf_count": pdf_count,
            "error_count": error_count,
        }

    def open_document(self, file_path):
        """Abre un PDF o JSON usando la aplicacion asociada en el equipo."""
        import os
        import platform
        import subprocess
        from pathlib import Path

        path = Path(file_path)
        if not path.is_file() or path.suffix.lower() not in {".pdf", ".json"}:
            return False, "El documento seleccionado no existe o no es compatible."

        try:
            if platform.system() == "Windows":
                os.startfile(str(path))
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            return True, f"Abriendo {path.name}..."
        except OSError as exc:
            return False, f"No se pudo abrir el documento: {exc}"
        
    def choose_directory(self):
        import webview
        if webview.windows:
            window = webview.windows[0]
            result = window.create_file_dialog(webview.FOLDER_DIALOG)
            if result:
                return result[0]
        return None
        
    # --- EMAIL MANAGEMENT ---
    def get_emails(self):
        return db.get_all_emails()

    def get_companies(self, include_recovery=True):
        return db.get_companies(include_recovery=include_recovery)

    @staticmethod
    def _validar_cuenta(email, server, port):
        import re

        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (email or "").strip()):
            return False, "Formato de correo inválido."
        try:
            puerto = int(port)
        except (TypeError, ValueError):
            return False, "Puerto inválido."
        if not 1 <= puerto <= 65535:
            return False, "Puerto fuera de rango (1-65535)."
        if not (server or "").strip():
            return False, "Servidor requerido."
        return True, ""

    def add_company(self, alias):
        return db.add_company(alias)

    def add_email(self, client, email, password_enc, server, port=993, start_date='2026-05-01'):
        valid, message = self._validar_cuenta(email, server, port)
        if not valid:
            return False, message
        if not (password_enc or "").strip():
            return False, "La contraseña es obligatoria."
        success, msg = db.add_email(client, email, password_enc, server, port, start_date)
        return success, msg

    def update_email(self, old_email, new_client, new_email, new_password, new_server, new_port, new_start_date='2026-05-01'):
        valid, message = self._validar_cuenta(new_email, new_server, new_port)
        if not valid:
            return False, message
        # Campo de contraseña vacío = mantener la actual (nunca se precarga en la UI).
        if not (new_password or "").strip():
            current = next(
                (item for item in db.get_all_emails() if item.get("email") == old_email),
                None,
            )
            if not current:
                return False, "La cuenta a editar no existe."
            new_password = current.get("password_encrypted", "")
        success, msg = db.update_email(old_email, new_client, new_email, new_password, new_server, new_port, new_start_date)
        return success, msg
        
    def delete_email(self, email):
        success, msg = db.delete_email(email)
        return success, msg
        
    # --- MANUAL REVIEW ---
    def get_manual_reviews(self):
        # Simulación de la base de datos de revisión
        # En producción esto vendría de CARPETA_REVISION
        return [
            {
                "id": 1,
                "pdf_path": str(CARPETA_PROCESADOS.parent / "04_Revision_Manual/doc_ilegible_1.pdf"),
                "uuid": "",
                "control": "",
                "date": "",
                "type": "03",
                "provider_name": "Procesado parcialmente",
                "provider_nit": ""
            }
        ]

    def save_manual_review(self, data):
        import json
        from pathlib import Path
        from src.backend.utils.config import CARPETA_DESCARGAS
        
        print(f"Revisión guardada: {data}")
        
        uuid = data.get("uuid", "UNKNOWN-UUID")
        
        # Build standard JSON based on the parsed data
        standard_json = {
            "identificacion": {
                "codigoGeneracion": uuid,
                "numeroControl": data.get("control", ""),
                "fecEmi": data.get("date", ""),
                "tipoDte": data.get("type", "03"),
            },
            "emisor": {
                "nombre": "Proveedor Desconocido" # En compra, el emisor es el proveedor
            },
            "receptor": {
                "nombre": data.get("provider_name", "Cliente_Manual")
            },
            "documentoRelacionado": [],
            "resumen": {
                "totalGravada": data.get("subtotal", 0),
                "subTotal": data.get("subtotal", 0),
                "tributos": [
                    {"codigo": "20", "descripcion": "Impuesto al Valor Agregado 13%", "valor": data.get("iva", 0)}
                ],
                "montoTotalOperacion": data.get("total", 0),
                "totalPagar": data.get("total", 0)
            },
            "selloRecepcion": {
                "selloRecepcion": data.get("sello", "")
            },
            "otros_impuestos_manuales": data.get("otros_impuestos", 0) # Campo custom para exportación
        }
        
        json_path = CARPETA_DESCARGAS / f"manual_{uuid}.json"
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(standard_json, f, indent=4)
            
        return True

    # --- GLOBAL CONTROLS ---
    def restart_service(self):
        print("Reiniciando motor...")
        self.orchestrator.stop()
        import time
        time.sleep(2)
        self.orchestrator.start()
        return True
        
    def shutdown_service(self):
        import webview
        print("Apagando aplicación...")
        if self.orchestrator.running:
            return False, "El proceso sigue activo. Deténgalo y espere a que termine."
        if webview.windows:
            webview.windows[0].destroy()
        return True, "Aplicación cerrada correctamente."
    
    def get_app_version(self):
        return "2.0.0"

    # --- SETTINGS ---
    def save_settings(self, data):
        import json
        from src.backend.utils.config import DATA_DIR
        from src.backend.utils.crypto import encrypt_data
        
        # Encriptar las API keys antes de guardar a disco
        secure_data = data.copy()
        for key_name in ("gemini", "deepseek", "llamaparse"):
            if key_name in secure_data and secure_data[key_name]:
                secure_data[key_name] = encrypt_data(secure_data[key_name])
        settings_file = DATA_DIR / "settings.json"
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(secure_data, f, indent=4)
        print("Configuración encriptada y guardada exitosamente.")
        return True
        
    def get_settings(self):
        import json
        from src.backend.utils.config import DATA_DIR
        from src.backend.utils.crypto import decrypt_data
        
        settings_file = DATA_DIR / "settings.json"
        if settings_file.exists():
            try:
                with open(settings_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    
                    # Desencriptar las llaves para enviarlas al frontend
                    for key_name in ("gemini", "deepseek", "llamaparse"):
                        if key_name in settings:
                            settings[key_name] = decrypt_data(settings[key_name])
                    # Claves de UI (p. ej. ultima carpeta de destino) pasan tal cual.
                    settings.setdefault("last_excel_dir", "")
                    return settings
            except Exception:
                pass

        return {"gemini": "", "deepseek": "", "llamaparse": "", "last_excel_dir": ""}

    # --- EXPLORER ---
    def get_other_documents(self, client_filter="", date_filter=""):
        from src.backend.utils.config import CARPETA_OTROS_DTES
        
        docs = []
        file_id = 1
        # La lista de Otros muestra los PDF originales (y JSON historicos):
        # ya no existe 05_Respaldo_PDF, el PDF vive junto a su documento.
        if not CARPETA_OTROS_DTES.exists():
            return docs
        for client_dir in CARPETA_OTROS_DTES.iterdir():
            if not client_dir.is_dir():
                continue
                
            client_name = client_dir.name
            if client_filter and client_filter.lower() not in client_name.lower():
                continue
                
            for date_dir in client_dir.iterdir():
                if not date_dir.is_dir():
                    continue
                    
                date_name = date_dir.name # YYYY-MM
                if date_filter and date_filter not in date_name:
                    continue
                    
                for file_path in date_dir.iterdir():
                    if not file_path.is_file():
                        continue
                        
                    file_type = file_path.suffix.lower().replace('.', '')
                    if file_type not in {'json', 'pdf'}:
                        continue
                        
                    docs.append({
                        "id": f"file_{file_id}",
                        "name": file_path.name,
                        "client": client_name,
                        "date": date_name,
                        "type": file_type,
                        "path": str(file_path.absolute())
                    })
                    file_id += 1
                    
        # Ordenamos descendente por id o asumiendo el orden
        return list(reversed(docs))
