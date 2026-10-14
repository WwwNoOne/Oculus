"""Cifrado local liviano para guardar API keys y secretos en disco.

No requiere dependencias externas: combina XOR con una clave derivada del
usuario del equipo y codificacion base64. Es ofuscacion local suficiente
para que las claves no queden en texto plano; no es un HSM.

El formato es "XOR1$<base64>". Los valores sin ese prefijo se devuelven
tal cual para no romper configuraciones previas en texto plano.
"""

import base64
import getpass
import hashlib

_SALT = "oculus-local-settings-v1"
_PREFIX = "XOR1$"


def _key():
    try:
        user = getpass.getuser()
    except Exception:
        user = "oculus"
    return hashlib.sha256(f"{_SALT}:{user}".encode("utf-8")).digest()


def encrypt_data(plain):
    """Cifra un texto y retorna el token almacenable. Nunca retorna None."""
    if plain is None:
        return ""
    key = _key()
    raw = str(plain).encode("utf-8")
    if not raw:
        return ""
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return _PREFIX + base64.urlsafe_b64encode(xored).decode("ascii")


def decrypt_data(token):
    """Descifra un token generado por encrypt_data. Retorna "" si falla."""
    if not token:
        return ""
    token = str(token)
    if token.startswith("gAAAA"):
        # Token Fernet de compilaciones anteriores (clave desconocida):
        # se intenta con la clave derivada local y si falla se descarta
        # para no enviar basura como API key.
        return _decrypt_legacy_fernet(token)
    if not token.startswith(_PREFIX):
        # Valor heredado en texto plano: se devuelve sin modificar.
        return token
    try:
        raw = base64.urlsafe_b64decode(token[len(_PREFIX):].encode("ascii"))
        key = _key()
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(raw)).decode("utf-8")
    except Exception:
        return ""


def _decrypt_legacy_fernet(token):
    """Mejor esfuerzo para tokens Fernet antiguos. Retorna "" si no se puede."""
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError:
        return ""
    try:
        fernet_key = base64.urlsafe_b64encode(_key())
        return Fernet(fernet_key).decrypt(token.encode("ascii")).decode("utf-8")
    except Exception:
        return ""
