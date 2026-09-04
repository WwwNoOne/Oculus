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
            
            # Migración para agregar la columna 'client' si venimos de versiones viejas
            try:
                cursor.execute("ALTER TABLE email_accounts ADD COLUMN client TEXT")
            except sqlite3.OperationalError:
                pass # La columna ya existe
            try:
                cursor.execute("ALTER TABLE email_accounts ADD COLUMN start_date TEXT DEFAULT '2026-05-01'")
            except sqlite3.OperationalError:
                pass # La columna ya existe

            cursor.execute('''
                INSERT OR IGNORE INTO companies (alias)
                SELECT DISTINCT TRIM(client) FROM email_accounts
                WHERE client IS NOT NULL AND TRIM(client) <> ''
            ''')
            
            conn.commit()

    def get_all_emails(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, email, client, password_encrypted, server, port, start_date, active, last_sync FROM email_accounts")
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_companies(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, alias, created_at FROM companies ORDER BY alias COLLATE NOCASE")
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

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

    def add_email(self, client, email, password_enc, server, port, start_date='2026-05-01'):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                if client and client.strip():
                    cursor.execute("INSERT OR IGNORE INTO companies (alias) VALUES (?)", (client.strip(),))
                cursor.execute(
                    "INSERT INTO email_accounts (email, client, password_encrypted, server, port, start_date) VALUES (?, ?, ?, ?, ?, ?)",
                    (email, client, password_enc, server, port, start_date)
                )
                conn.commit()
                return True, "Cuenta añadida correctamente"
            except sqlite3.IntegrityError:
                return False, "La cuenta ya existe"
            except Exception as e:
                return False, str(e)

    def update_email(self, old_email, new_client, new_email, new_password, new_server, new_port, new_start_date='2026-05-01'):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                if new_client and new_client.strip():
                    cursor.execute("INSERT OR IGNORE INTO companies (alias) VALUES (?)", (new_client.strip(),))
                cursor.execute('''
                    UPDATE email_accounts 
                    SET client = ?, email = ?, password_encrypted = ?, server = ?, port = ?, start_date = ?
                    WHERE email = ?
                ''', (new_client, new_email, new_password, new_server, new_port, new_start_date, old_email))
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
            cursor.execute("UPDATE email_accounts SET active = ? WHERE email = ?", (active, email))
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
