from src.backend.database.db_manager import db
from src.backend.services.dte_service import DTEService
from src.backend.services.orchestrator import Orchestrator
from src.backend.utils.config import (
    CARPETA_PROCESADOS,
    CARPETA_OTROS_DTES,
    CARPETA_RESPALDO_PDF,
    CARPETA_DUPLICADOS,
    DATA_DIR,
    DB_PATH,
    CARPETA_DESCARGAS_RESPALDO,
)

class Api:
    def __init__(self):
        self.dte_service = DTEService()
        self.orchestrator = Orchestrator()
        self.dte_service.migrate_legacy_documents()
        self.recovery_thread = None
        self.recovery_stop_requested = False
        self.recovery_status = {"status": "IDLE", "message": ""}
    
    def get_stats(self):
        """Obtiene las estadísticas reales de la base de datos"""
        return db.get_stats()

    def get_telemetry(self):
        """Retorna telemetría en vivo del orquestador"""
        return {
            "status": self.orchestrator.current_status,
            "docs_downloaded": self.orchestrator.docs_downloaded,
            "docs_processed": self.orchestrator.docs_processed,
            "errors": self.orchestrator.errors,
            "uptime_seconds": 0 if not self.orchestrator.start_time else (
                __import__('time').time() - self.orchestrator.start_time
            )
        }

    def start_processing(self, account_email=None):
        """Inicia el pipeline de procesamiento real (ahora con el Orquestador)"""
        print("Iniciando procesamiento...")
        self.orchestrator.start(account_email)
        return "Motor iniciado en segundo plano. Monitoreando la cuenta seleccionada..." if account_email else "Motor iniciado en segundo plano. Monitoreando todas las cuentas..."

    def stop_processing(self):
        """Solicita una detencion ordenada y espera al final de la operacion actual."""
        self.orchestrator.stop(wait=True)
        return True, "Proceso detenido correctamente."

    def start_recovery(self, account_email, target_alias, start_date, end_date):
        import threading
        from datetime import date
        from src.backend.database.db_manager import db
        from src.backend.services.email_service import EmailService

        if self.orchestrator.running or (self.recovery_thread and self.recovery_thread.is_alive()):
            return False, "Detenga el proceso normal antes de iniciar una recuperación."
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
            if end <= start:
                return False, "La fecha final debe ser posterior a la fecha inicial."
        except (TypeError, ValueError):
            return False, "Rango de fechas inválido."
        account = next((item for item in db.get_all_emails() if item.get("email") == account_email), None)
        if not account or not target_alias.strip():
            return False, "Seleccione una cuenta y un alias de respaldo."

        recovery_dir = CARPETA_DESCARGAS_RESPALDO / target_alias.strip()
        self.recovery_stop_requested = False
        self.recovery_status = {"status": "RUNNING", "message": "Recuperación en curso"}

        def worker():
            try:
                mail = EmailService(str(recovery_dir), str(recovery_dir / "adjuntos_otros"))
                result = mail.descargar_correos(
                    cuenta=target_alias.strip(), servidor=account["server"], puerto=account["port"],
                    usuario=account["email"], password=account["password_encrypted"],
                    protocolo="POP3" if account["port"] == 995 else "IMAP", estado_key=account["email"],
                    start_date=start_date, end_date=end_date,
                    should_stop=lambda: self.recovery_stop_requested,
                )
                if not self.recovery_stop_requested:
                    result.update(self.dte_service.process_downloads(
                        client_filter=target_alias.strip(), source_dir=recovery_dir,
                        destination_alias=target_alias.strip(),
                    ))
                self.recovery_status = {"status": "IDLE", "message": f"Recuperación finalizada: {result}"}
            except Exception as exc:
                self.recovery_status = {"status": "ERROR", "message": str(exc)}

        self.recovery_thread = threading.Thread(target=worker, daemon=True)
        self.recovery_thread.start()
        return True, "Recuperación iniciada."

    def get_recovery_status(self):
        return self.recovery_status

    def stop_recovery(self):
        self.recovery_stop_requested = True
        return True, "La recuperación terminará el mensaje actual."
    
    def get_clients(self):
        if not CARPETA_PROCESADOS.exists(): return []
        return sorted(f.name for f in CARPETA_PROCESADOS.iterdir() if f.is_dir())
        
    def get_months(self, client_name):
        client_path = CARPETA_PROCESADOS / client_name
        if not client_path.exists(): return []
        return sorted(f.name for f in client_path.iterdir() if f.is_dir())
        
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
        selected_path = None

        if client_path and client_path.exists():
            periods = sorted(folder.name for folder in client_path.iterdir() if folder.is_dir())
            if month_year:
                selected_path = client_path / month_year
                if selected_path.exists():
                    json_count = len(list(selected_path.glob("*.json")))
                    pdf_count = len(list(selected_path.glob("*.pdf")))

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

    def get_companies(self):
        return db.get_companies()

    def add_company(self, alias):
        return db.add_company(alias)

    def add_email(self, client, email, password_enc, server, port=993, start_date='2026-05-01'):
        success, msg = db.add_email(client, email, password_enc, server, port, start_date)
        return success, msg
        
    def update_email(self, old_email, new_client, new_email, new_password, new_server, new_port, new_start_date='2026-05-01'):
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
        if "gemini" in secure_data and secure_data["gemini"]:
            secure_data["gemini"] = encrypt_data(secure_data["gemini"])
        if "deepseek" in secure_data and secure_data["deepseek"]:
            secure_data["deepseek"] = encrypt_data(secure_data["deepseek"])
        settings_file = DATA_DIR / "settings.json"
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(secure_data, f, indent=4)
        print("Configuración de API encriptada y guardada exitosamente.")
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
                    if "gemini" in settings:
                        settings["gemini"] = decrypt_data(settings["gemini"])
                    if "deepseek" in settings:
                        settings["deepseek"] = decrypt_data(settings["deepseek"])
                    return settings
            except Exception:
                pass
                
        return {"gemini": "", "deepseek": ""}

    # --- EXPLORER ---
    def get_other_documents(self, client_filter="", date_filter=""):
        from src.backend.utils.config import CARPETA_OTROS_DTES
        
        docs = []
        file_id = 1
        # La lista de Otros muestra JSON; los PDF se conservan como respaldo
        # en 05_Respaldo_PDF y no deben mezclarse en esta vista.
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
                    if file_type != 'json':
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
