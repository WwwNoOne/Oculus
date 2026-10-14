import time
import threading
import datetime
from collections import deque
from src.backend.database.db_manager import db
from src.backend.services.email_service import EmailService
from src.backend.services.dte_service import DTEService
from src.backend.utils.config import CARPETA_DESCARGAS


class Orchestrator:
    """Motor de descarga y procesamiento con telemetria de progreso real.

    Alcance (scope): None o "" = todas las cuentas; un alias de empresa filtra
    por `client`; un email filtra por esa cuenta (compatibilidad).
    """

    PHASE_IDLE = "IDLE"
    PHASE_DOWNLOADING = "DESCARGANDO"
    PHASE_PROCESSING = "PROCESANDO"
    PHASE_SLEEPING = "DURMIENDO"
    PHASE_STOPPING = "DETENIENDO"

    def __init__(self):
        self.running = False
        self.thread = None
        self.email_service = EmailService(str(CARPETA_DESCARGAS))
        self.dte_service = DTEService()

        # Progreso real
        self.phase = self.PHASE_IDLE
        self.current_status = self.phase  # alias historico
        self.total_accounts = 0
        self.accounts_done = 0
        self.current_account = ""
        self.docs_total = 0
        self.docs_done = 0

        # Contadores del ciclo actual
        self.docs_downloaded = 0
        self.docs_processed = 0
        self.duplicates = 0
        self.errors = 0

        self.start_time = None
        self.company_scope = None
        self.last_message = "Motor detenido."
        self.recent_messages = deque(maxlen=10)

    # --- utilidades internas ---
    def _set_phase(self, phase):
        self.phase = phase
        self.current_status = phase

    def _say(self, message):
        self.last_message = message
        try:
            self.recent_messages.append({
                "time": datetime.datetime.now().isoformat(timespec="seconds"),
                "message": message,
            })
        except Exception:
            pass
        print(f"[Orquestador] {message}")

    def _should_stop(self):
        return not self.running

    def _sleep_interruptible(self, seconds):
        for _ in range(int(seconds)):
            if not self.running:
                break
            time.sleep(1)

    def _pending_docs(self, client_filter=None):
        """Cuenta los archivos pendientes en descargas aplicando el mismo filtro
        que DTEService.process_downloads."""
        try:
            archivos = list(CARPETA_DESCARGAS.glob("*.*"))
        except OSError:
            return []
        if client_filter:
            lowered = client_filter.casefold()
            archivos = [p for p in archivos if p.name.casefold().startswith(f"{lowered}_")]
        docs = []
        for path in archivos:
            suffix = path.suffix.lower()
            if suffix == ".pdf":
                docs.append(path)
            elif suffix == ".json" and not path.name.lower().endswith("_estado.json"):
                docs.append(path)
        return docs

    def progress_percent(self):
        if self.phase == self.PHASE_DOWNLOADING:
            if self.total_accounts <= 0:
                return 5.0
            return round(min(1.0, self.accounts_done / self.total_accounts) * 40.0, 1)
        if self.phase == self.PHASE_PROCESSING:
            if self.docs_total <= 0:
                return 100.0
            return round(40.0 + min(1.0, self.docs_done / self.docs_total) * 60.0, 1)
        if self.phase == self.PHASE_SLEEPING:
            return 100.0
        return 0.0

    def get_telemetry(self):
        uptime = 0 if not self.start_time else (time.time() - self.start_time)
        return {
            "status": self.phase,
            "phase": self.phase,
            "total_accounts": self.total_accounts,
            "accounts_done": self.accounts_done,
            "current_account": self.current_account,
            "docs_total": self.docs_total,
            "docs_done": self.docs_done,
            "progress_percent": self.progress_percent(),
            "docs_downloaded": self.docs_downloaded,
            "docs_processed": self.docs_processed,
            "duplicates": self.duplicates,
            "errors": self.errors,
            "uptime_seconds": uptime,
            "last_message": self.last_message,
            "recent_messages": list(self.recent_messages),
            "scope": self.company_scope,
        }

    # --- control ---
    def start(self, company_alias=None):
        if self.running:
            return
        scope = (company_alias or "").strip() or None
        self.company_scope = scope
        self.start_time = time.time()
        self.total_accounts = 0
        self.accounts_done = 0
        self.current_account = ""
        self.docs_total = 0
        self.docs_done = 0
        self.docs_downloaded = 0
        self.docs_processed = 0
        self.duplicates = 0
        self.errors = 0
        self._set_phase(self.PHASE_DOWNLOADING)
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self._say("Motor iniciado en segundo plano.")

    def stop(self, wait=True):
        if self.running:
            self._say("Apagando el motor. Esperando al final de la operacion actual...")
            self.running = False
            self._set_phase(self.PHASE_STOPPING)
            if wait and self.thread and self.thread is not threading.current_thread():
                self.thread.join()

    # --- ciclo principal ---
    def _loop(self):
        while self.running:
            try:
                self._say("Iniciando ciclo.")
                self._set_phase(self.PHASE_DOWNLOADING)

                # Alcance: empresa (por client) o email (compatibilidad).
                cuentas = db.get_all_emails()
                scope = self.company_scope
                scope_kind = "all"
                scope_label = "todas las cuentas"
                if scope:
                    by_email = [c for c in cuentas if (c.get("email") or "").lower() == scope.lower()]
                    if by_email:
                        cuentas = by_email
                        scope_kind = "email"
                        scope_label = f"la cuenta {scope}"
                    else:
                        cuentas = [
                            c for c in cuentas
                            if (c.get("client") or "").strip().lower() == scope.lower()
                        ]
                        scope_kind = "company"
                        scope_label = f"la empresa {scope}"
                self._say(f"Alcance: {scope_label} ({len(cuentas)} cuentas).")

                self.total_accounts = len(cuentas)
                self.accounts_done = 0

                # FASE 1: Descarga de correos (0-40 %)
                for cuenta in cuentas:
                    if not self.running:
                        break

                    email = cuenta["email"]
                    client_alias = cuenta.get("client") or email.split("@")[0]
                    password = cuenta["password_encrypted"]
                    servidor = cuenta["server"]
                    puerto = cuenta["port"]
                    auth_type = (cuenta.get("auth_type") or "password").lower()

                    # Cuentas OAuth: token fresco + IMAP forzado (XOAUTH2 no existe en POP3).
                    oauth_token = None
                    if auth_type in ("google", "microsoft"):
                        try:
                            from src.backend.services import oauth_service
                            oauth_token = oauth_service.obtener_token(email, auth_type)
                        except Exception as e:
                            self._say(f"OAuth de {email} vencido o sin sesion: {e}")
                            db.update_email_status(email, 0)
                            self.errors += 1
                            self.accounts_done += 1
                            continue
                        puerto = 993
                        protocolo = "IMAP"
                    else:
                        protocolo = "POP3" if puerto == 995 else "IMAP"

                    self.current_account = email
                    self._say(f"Descargando {email} ({self.accounts_done + 1}/{self.total_accounts}).")

                    try:
                        resultados = self.email_service.descargar_correos(
                            cuenta=client_alias,
                            servidor=servidor,
                            puerto=puerto,
                            usuario=email,
                            password=password,
                            protocolo=protocolo,
                            estado_key=email,
                            start_date=cuenta.get("start_date") or "2026-09-01",
                            should_stop=self._should_stop,
                            auth_type=auth_type,
                            oauth_token=oauth_token,
                        )
                        self._say(f"Cuenta {email}: {resultados}")
                        db.update_email_status(email, 1)  # Marcar como activa/ok

                        self.docs_downloaded += resultados.get("descargados", 0)
                        self.errors += resultados.get("errores", 0)
                    except Exception as e:
                        self._say(f"Error de autenticacion o conexion descargando {email}: {e}")
                        db.update_email_status(email, 0)
                        self.errors += 1

                    self.accounts_done += 1
                    self.current_account = ""

                    # Pausa tactica para no saturar el servidor (interrumpible).
                    if self.running:
                        self._sleep_interruptible(10)

                # FASE 2: Procesamiento y archivado (40-100 %)
                if self.running:
                    self._set_phase(self.PHASE_PROCESSING)
                    self._say("Procesando descargas acumuladas...")

                    client_filter = None
                    if scope_kind == "company":
                        client_filter = scope
                    elif scope_kind == "email" and cuentas:
                        client_filter = (cuentas[0].get("client") or None)

                    pending = self._pending_docs(client_filter)
                    self.docs_total = len(pending)
                    self.docs_done = 0

                    def on_progress(done, total):
                        self.docs_done = done
                        if total:
                            self.docs_total = total

                    res = self.dte_service.process_downloads(
                        client_filter=client_filter,
                        should_stop=self._should_stop,
                        on_progress=on_progress,
                    )
                    self.docs_processed += res.get("procesados_json", 0) + res.get("procesados_ocr", 0)
                    self.duplicates += res.get("duplicados", 0)
                    self.errors += res.get("errores", 0)
                    self._say(f"Resultados del procesamiento: {res}")
                    self._say("Ejecutando mantenimiento y migracion segura...")
                    self.dte_service.migrate_legacy_documents()

            except Exception as e:
                self.errors += 1
                self._say(f"Error critico en el ciclo: {e}")

            # FASE 3: Pausa profunda antes del siguiente ciclo (25 minutos)
            if self.running:
                espera_segundos = 1500
                self._set_phase(self.PHASE_SLEEPING)
                self._say(f"Ciclo finalizado. Durmiendo {espera_segundos}s.")
                self._sleep_interruptible(espera_segundos)

        self._set_phase(self.PHASE_IDLE)
        self.current_account = ""
        self._say("Motor detenido exitosamente.")
