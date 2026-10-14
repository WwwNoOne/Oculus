"""Migra las cuentas de correo del programa anterior a la BD actual.

Uso:
    .\\.venv\\Scripts\\python.exe migrar_cuentas.py [ruta_origen.db]

Por defecto lee PRUEBAS/db/oculus.db y escribe en data/ (la BD en uso).
Solo inserta las cuentas que no existen (por email). No borra ni modifica
nada del origen. Las contraseñas se copian tal cual estaban guardadas
(en claro, igual que las maneja la app actual).
"""
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

ORIGEN_DEFECTO = BASE / "PRUEBAS" / "db" / "oculus.db"


def main() -> int:
    origen = Path(sys.argv[1]) if len(sys.argv) > 1 else ORIGEN_DEFECTO
    if not origen.is_file():
        print(f"[!] No existe la BD origen: {origen}")
        return 1

    from src.backend.database.db_manager import db as destino

    conn = sqlite3.connect(str(origen))
    try:
        filas = conn.execute(
            "SELECT email, client, password_encrypted, server, port, start_date"
            " FROM email_accounts ORDER BY email"
        ).fetchall()
    except sqlite3.Error as e:
        print(f"[!] No se pudo leer la BD origen: {e}")
        return 1
    finally:
        conn.close()

    if not filas:
        print("[!] La BD origen no tiene cuentas.")
        return 1

    nuevas, existentes, fallos = 0, 0, []
    for email, client, password, server, port, start_date in filas:
        ok, msg = destino.add_email(
            client or "", email, password or "",
            server or "", port or 993, start_date or "2026-05-01",
        )
        if ok:
            nuevas += 1
            print(f"[+] {email} ({client})")
        elif "ya existe" in msg:
            existentes += 1
            print(f"[=] {email} ya existe, se conserva")
        else:
            fallos.append(email)
            print(f"[!] {email}: {msg}")

    print(f"\nMigradas: {nuevas} | Ya existian: {existentes} | Fallos: {len(fallos)}")
    if fallos:
        print("Fallidas:", ", ".join(fallos))
        return 1
    print("Las contraseñas viajan en claro (igual que la app actual las guarda).")
    print("Verifica cada cuenta con su proveedor si alguna deja de conectar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
