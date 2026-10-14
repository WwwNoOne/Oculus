import sqlite3
from pathlib import Path
from src.backend.utils.config import DB_PATH

class DBManager:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()
        
    def _get_connection(self):
        # Usar check_same_thread=False si se usa desde múltiples hilos en Pywebview
        return sqlite3.connect(self.db_path, check_same_thread=False)
        
    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Tabla de cuentas de correo para gestión desde la interfaz
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS email_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    client TEXT,
                    password_encrypted TEXT NOT NULL,
                    server TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    start_date TEXT DEFAULT '2026-05-01',
                    active BOOLEAN DEFAULT 1,
                    last_sync DATETIME
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS companies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alias TEXT UNIQUE COLLATE NOCASE NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Tabla de auditoría e historial de DTEs procesados
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS extraction_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    dte_code TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    error_msg TEXT
                )
            ''')

            # Documentos aprobados por la IA: fuente de datos del libro de compras.
            # El PDF original vive en 02_Procesados/<alias>/<mes>/; los JSON
            # intermedios se eliminan tras guardar la fila.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dte_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alias TEXT NOT NULL,
                    periodo TEXT NOT NULL,
                    codigo_generacion TEXT NOT NULL UNIQUE,
                    tipo_dte TEXT NOT NULL,
                    fecha_emision TEXT NOT NULL,
                    numero_control TEXT DEFAULT '',
                    pdf_name TEXT DEFAULT '',
                    data_json TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_dte_alias_periodo
                ON dte_documents(alias, periodo)
            ''')
            
            # Migración para agregar la columna 'client' si venimos de versiones viejas
            try:
                cursor.execute("ALTER TABLE email_accounts ADD COLUMN client TEXT")
            except sqlite3.OperationalError:
                pass # La columna ya existe
            try:
                cursor.execute("ALTER TABLE email_accounts ADD COLUMN start_date TEXT DEFAULT '2026-05-01'")
            except sqlite3.OperationalError:
                pass # La columna ya existe
            # Los alias de recuperacion se marcan como 'recovery' para no
            # ensuciar la vista de Gestion de DTEs.
            try:
                cursor.execute("ALTER TABLE companies ADD COLUMN kind TEXT DEFAULT 'normal'")
            except sqlite3.OperationalError:
                pass # La columna ya existe
            # Cuentas OAuth (login oficial) vs contrasena.
            try:
                cursor.execute("ALTER TABLE email_accounts ADD COLUMN auth_type TEXT DEFAULT 'password'")
            except sqlite3.OperationalError:
                pass # La columna ya existe
            try:
                cursor.execute("UPDATE companies SET kind = 'normal' WHERE kind IS NULL OR TRIM(kind) = ''")
            except sqlite3.OperationalError:
                pass

            cursor.execute('''
                INSERT OR IGNORE INTO companies (alias)
                SELECT DISTINCT TRIM(client) FROM email_accounts
                WHERE client IS NOT NULL AND TRIM(client) <> ''
            ''')
            
            conn.commit()

    def get_all_emails(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, email, client, password_encrypted, server, port, start_date, active, last_sync, auth_type FROM email_accounts")
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_companies(self, include_recovery=True):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                if include_recovery:
                    cursor.execute("SELECT id, alias, created_at FROM companies ORDER BY alias COLLATE NOCASE")
                else:
                    cursor.execute(
                        "SELECT id, alias, created_at FROM companies "
                        "WHERE kind IS NULL OR kind <> 'recovery' ORDER BY alias COLLATE NOCASE"
                    )
            except sqlite3.OperationalError:
                cursor.execute("SELECT id, alias, created_at FROM companies ORDER BY alias COLLATE NOCASE")
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_company_kind(self, alias):
        """Retorna 'recovery', 'normal' o None si el alias no esta registrado."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT kind FROM companies WHERE alias = ? COLLATE NOCASE", ((alias or "").strip(),))
                row = cursor.fetchone()
            except sqlite3.OperationalError:
                return None
            if not row:
                return None
            return (row[0] or "normal").strip().lower() or "normal"

    def set_company_kind(self, alias, kind):
        """Registra el alias si no existe y le asigna el tipo ('normal' | 'recovery')."""
        alias = (alias or "").strip()
        kind = "recovery" if (kind or "").strip().lower() == "recovery" else "normal"
        if not alias:
            return False
        with self._get_connection() as conn:
            try:
                conn.execute("INSERT OR IGNORE INTO companies (alias, kind) VALUES (?, ?)", (alias, kind))
                conn.execute("UPDATE companies SET kind = ? WHERE alias = ? COLLATE NOCASE", (kind, alias))
                conn.commit()
                return True
            except sqlite3.OperationalError:
                return False

    def remove_company(self, alias):
        """Elimina el registro del alias. Nunca toca email_accounts."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM companies WHERE alias = ? COLLATE NOCASE", ((alias or "").strip(),))
            conn.commit()
            return cursor.rowcount > 0

    # --- DOCUMENTOS (filas del libro de compras) ---
    def dte_exists(self, codigo):
        """True si el codigoGeneracion ya tiene fila (deduplicacion por BD)."""
        codigo = (codigo or "").strip().upper()
        if not codigo:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM dte_documents WHERE codigo_generacion = ?", (codigo,)
            )
            return cursor.fetchone() is not None

    def dte_upsert(self, alias, periodo, codigo, tipo_dte, fecha_emision,
                   numero_control="", pdf_name="", data_json="{}"):
        """Inserta la fila del documento. Retorna True si se inserto,
        False si el codigo ya existia (duplicado)."""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO dte_documents
                       (alias, periodo, codigo_generacion, tipo_dte, fecha_emision,
                        numero_control, pdf_name, data_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (alias, periodo, (codigo or "").strip().upper(), tipo_dte,
                     fecha_emision, numero_control or "", pdf_name or "", data_json or "{}"),
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception:
            return False

    def dte_set_pdf(self, codigo, pdf_name):
        """Vincula el PDF a una fila existente (migracion de respaldos)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE dte_documents SET pdf_name = ? WHERE codigo_generacion = ?",
                (pdf_name or "", (codigo or "").strip().upper()),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_dte_rows(self, alias, periodo):
        """Filas del libro para un alias y periodo, ordenadas por fecha e id."""
        import json as _json

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT codigo_generacion, tipo_dte, fecha_emision, numero_control,
                          pdf_name, data_json
                   FROM dte_documents
                   WHERE alias = ? COLLATE NOCASE AND periodo = ?
                   ORDER BY fecha_emision, id""",
                ((alias or "").strip(), periodo or ""),
            )
            columns = [column[0] for column in cursor.description]
            rows = []
            for record in cursor.fetchall():
                row = dict(zip(columns, record))
                try:
                    row["data"] = _json.loads(row.get("data_json") or "{}")
                except Exception:
                    row["data"] = {}
                rows.append(row)
            return rows

    def count_dte_rows(self, alias, periodo):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM dte_documents WHERE alias = ? COLLATE NOCASE AND periodo = ?",
                ((alias or "").strip(), periodo or ""),
            )
            return cursor.fetchone()[0]

    def distinct_periods(self, alias):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT periodo FROM dte_documents WHERE alias = ? COLLATE NOCASE ORDER BY periodo",
                ((alias or "").strip(),),
            )
            return [row[0] for row in cursor.fetchall() if row[0]]

    def add_company(self, alias):
        alias = (alias or "").strip()
        if not alias:
            return False, "El alias de la empresa es obligatorio"
        with self._get_connection() as conn:
            try:
                conn.execute("INSERT INTO companies (alias) VALUES (?)", (alias,))
                conn.commit()
                return True, "Empresa registrada correctamente"
            except sqlite3.IntegrityError:
                return False, "Ese alias ya está registrado"

    def add_email(self, client, email, password_enc, server, port, start_date='2026-05-01', auth_type='password'):
        auth_type = (auth_type or 'password').strip().lower()
        if auth_type not in ('password', 'google', 'microsoft'):
            auth_type = 'password'
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                if client and client.strip():
                    cursor.execute("INSERT OR IGNORE INTO companies (alias) VALUES (?)", (client.strip(),))
                cursor.execute(
                    "INSERT INTO email_accounts (email, client, password_encrypted, server, port, start_date, auth_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (email, client, password_enc, server, port, start_date, auth_type)
                )
                conn.commit()
                return True, "Cuenta añadida correctamente"
            except sqlite3.IntegrityError:
                return False, "La cuenta ya existe"
            except Exception as e:
                return False, str(e)

    def update_email(self, old_email, new_client, new_email, new_password, new_server, new_port, new_start_date='2026-05-01', auth_type=None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                if auth_type is None:
                    cursor.execute("SELECT auth_type FROM email_accounts WHERE email = ?", (old_email,))
                    row = cursor.fetchone()
                    auth_type = (row[0] if row and row[0] else 'password')
                auth_type = (auth_type or 'password').strip().lower()
                if auth_type not in ('password', 'google', 'microsoft'):
                    auth_type = 'password'
                if new_client and new_client.strip():
                    cursor.execute("INSERT OR IGNORE INTO companies (alias) VALUES (?)", (new_client.strip(),))
                cursor.execute('''
                    UPDATE email_accounts
                    SET client = ?, email = ?, password_encrypted = ?, server = ?, port = ?, start_date = ?, auth_type = ?
                    WHERE email = ?
                ''', (new_client, new_email, new_password, new_server, new_port, new_start_date, auth_type, old_email))
                conn.commit()
                return True, "Cuenta actualizada correctamente"
            except sqlite3.IntegrityError:
                return False, "La nueva cuenta de correo ya existe"
            except Exception as e:
                return False, str(e)

    def delete_email(self, email):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM email_accounts WHERE email = ?", (email,))
                conn.commit()
                return True, "Cuenta eliminada correctamente"
            except Exception as e:
                return False, str(e)

    def update_email_status(self, email, active: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE email_accounts SET active = ?, last_sync = CURRENT_TIMESTAMP WHERE email = ?",
                (active, email),
            )
            conn.commit()
                
    def log_extraction(self, filename, status, dte_code=None, error_msg=None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO extraction_logs (filename, status, dte_code, error_msg) VALUES (?, ?, ?, ?)",
                (filename, status, dte_code, error_msg)
            )
            conn.commit()

    def get_stats(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM extraction_logs WHERE status='VALID_DTE'")
            processed = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM extraction_logs WHERE status='ERROR' OR status='NEEDS_REVIEW'")
            errors = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM extraction_logs WHERE status='OTHER_DTE'")
            others = cursor.fetchone()[0]
            
            return {
                "processed": processed,
                "errors": errors,
                "others": others,
                "pending": 0 # This would be calculated from the physical download folder
            }

# Instancia global
db = DBManager()
