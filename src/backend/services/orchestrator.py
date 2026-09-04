import time
import threading
from src.backend.database.db_manager import db
from src.backend.services.email_service import EmailService
from src.backend.services.dte_service import DTEService
from src.backend.utils.config import CARPETA_DESCARGAS

class Orchestrator:
    def __init__(self):
        self.running = False
        self.thread = None
        self.email_service = EmailService(str(CARPETA_DESCARGAS))
        self.dte_service = DTEService()
        
        # Telemetría
        self.current_status = "IDLE"
        self.docs_downloaded = 0
        self.docs_processed = 0
        self.errors = 0
        self.start_time = None
        self.account_scope = None

    def start(self, account_email=None):
        if not self.running:
            self.account_scope = account_email or None
            import time
            self.start_time = time.time()
            self.current_status = "STARTING"
            self.running = True
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
            print("[Orquestador] Motor iniciado en segundo plano.")
            
    def stop(self, wait=True):
        if self.running:
            print("[Orquestador] Apagando el motor. Esperando al final del ciclo actual...")
            self.running = False
            self.current_status = "STOPPING"
            if wait and self.thread and self.thread is not threading.current_thread():
                self.thread.join()
            
    def _loop(self):
        while self.running:
            try:
                print("\n=== [Orquestador] Iniciando Ciclo ===")
                self.current_status = "DOWNLOADING"
                
                # FASE 1: Descarga de Correos
                cuentas = db.get_all_emails()
                if self.account_scope:
                    cuentas = [cuenta for cuenta in cuentas if cuenta.get('email') == self.account_scope]
                    print(f"[Orquestador] Alcance: solo {self.account_scope}")
                
                for cuenta in cuentas:
                    if not self.running: break
                    
                    email = cuenta['email']
                    client_alias = cuenta.get('client') or email.split('@')[0]
                    password = cuenta['password_encrypted']
                    servidor = cuenta['server']
                    puerto = cuenta['port']
                    
                    # Detección Automática de Protocolo
                    protocolo = "POP3" if puerto == 995 else "IMAP"
                    
                    try:
                        resultados = self.email_service.descargar_correos(
                            cuenta=client_alias,
                            servidor=servidor,
                            puerto=puerto,
                            usuario=email,
                            password=password,
                            protocolo=protocolo,
                            estado_key=email,
                            start_date=cuenta.get('start_date') or '2026-05-01'
                        )
                        print(f"[Orquestador] Cuenta {email}: {resultados}")
                        db.update_email_status(email, 1) # Marcar como activa/ok
                        
                        self.docs_downloaded += resultados.get("descargados", 0)
                        self.errors += resultados.get("errores", 0)
                    except Exception as e:
                        print(f"[Orquestador] Error de autenticación o conexión descargando {email}: {e}")
                        db.update_email_status(email, 0) # Desactivar cuenta por error
                        self.errors += 1
                        # Continuar con la siguiente cuenta sin detener el ciclo principal
                        
                    # Pausa Táctica para evitar saturación de red o del servidor IMAP/POP3
                    if self.running:
                        print("  [Pausing 10s...]")
                        time.sleep(10)
                        
                # FASE 2 y 3: Procesamiento y Archivado
                if self.running:
                    self.current_status = "PROCESSING"
                    print("\n[Orquestador] Procesando descargas acumuladas...")
                    selected_alias = None
                    if self.account_scope:
                        selected = next((account for account in cuentas if account.get('email') == self.account_scope), None)
                        selected_alias = (selected or {}).get('client')
                    res = self.dte_service.process_downloads(client_filter=selected_alias)
                    self.docs_processed += res.get("procesados_json", 0) + res.get("procesados_ocr", 0)
                    self.errors += res.get("errores", 0)
                    print(f"[Orquestador] Resultados del procesamiento: {res}")
                    print("[Orquestador] Ejecutando mantenimiento y migracion segura...")
                    self.dte_service.migrate_legacy_documents()
                
            except Exception as e:
                print(f"[Orquestador] Error crítico en el ciclo: {e}")
                
            # FASE 4: Pausa profunda antes del siguiente ciclo (25 minutos)
            if self.running:
                espera_segundos = 1500
                self.current_status = "SLEEPING"
                print(f"\n=== [Orquestador] Ciclo Finalizado. Durmiendo {espera_segundos}s ===")
                # Sleep en pequeños bloques para responder rápido al comando de Stop
                for _ in range(espera_segundos):
                    if not self.running: break
                    time.sleep(1)
                    
        self.current_status = "IDLE"
        print("[Orquestador] Motor detenido exitosamente.")
