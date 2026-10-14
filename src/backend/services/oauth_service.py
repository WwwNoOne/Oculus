"""Autenticacion oficial OAuth2 (Gmail/Outlook) + contrasena para dominios custom.

- Gmail/Outlook: abre el navegador con el login oficial y usa XOAUTH2 por IMAP.
  Sin contrasenas de aplicacion.
- Dominio custom: correo + contrasena por IMAP SSL (o forzar Microsoft 365).
- Los secretos OAuth (refresh tokens) viven en keyring (Credential Manager);
  nunca se guardan en la BD. Las contrasenas custom siguen en la BD como antes.

Requiere: pip install keyring msal google-auth-oauthlib google-auth
"""
import imaplib
import json

APP = "oculus_dte"

# Gmail por IMAP exige este scope (gmail.readonly solo sirve con la Gmail API).
GOOGLE_SCOPES = ["https://mail.google.com/"]
MS_AUTHORITY = "https://login.microsoftonline.com/common"
MS_SCOPES = ["https://outlook.office.com/IMAP.AccessAsUser.All"]

PROVEEDORES = {
    "gmail.com": ("google", "imap.gmail.com"),
    "googlemail.com": ("google", "imap.gmail.com"),
    "outlook.com": ("microsoft", "outlook.office365.com"),
    "hotmail.com": ("microsoft", "outlook.office365.com"),
    "live.com": ("microsoft", "outlook.office365.com"),
    "msn.com": ("microsoft", "outlook.office365.com"),
}

try:
    import keyring
except ImportError:
    keyring = None

try:
    import msal
except ImportError:
    msal = None

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
except ImportError:
    InstalledAppFlow = Credentials = Request = None


# ---------- Credenciales de aplicacion (del usuario, una sola vez) ----------
def _ajustes_oauth():
    """Lee client_id/secret de settings.json (cifrado) o variables de entorno."""
    import os
    from src.backend.utils.crypto import decrypt_data

    ajustes = {"google_client_id": "", "google_client_secret": "",
               "microsoft_client_id": ""}
    try:
        from src.backend.utils.config import DATA_DIR

        ruta = DATA_DIR / "settings.json"
        if ruta.exists():
            with open(ruta, "r", encoding="utf-8") as f:
                guardados = json.load(f)
            for clave in ajustes:
                if guardados.get(clave):
                    ajustes[clave] = guardados[clave]
            if ajustes.get("google_client_secret"):
                ajustes["google_client_secret"] = decrypt_data(ajustes["google_client_secret"])
    except Exception:
        pass
    ajustes["google_client_id"] = ajustes["google_client_id"] or os.getenv("GOOGLE_CLIENT_ID", "")
    ajustes["google_client_secret"] = ajustes["google_client_secret"] or os.getenv("GOOGLE_CLIENT_SECRET", "")
    ajustes["microsoft_client_id"] = ajustes["microsoft_client_id"] or os.getenv("MS_CLIENT_ID", "")
    return ajustes


def detectar_proveedor(correo, forzar_microsoft=False):
    """Retorna (auth, host). auth en {'google', 'microsoft', 'password'}."""
    dominio = (correo or "").split("@")[-1].lower()
    auth, host = PROVEEDORES.get(dominio, ("password", f"imap.{dominio}"))
    if forzar_microsoft:
        auth, host = "microsoft", "outlook.office365.com"
    return auth, host


def xoauth2_string(correo, token) -> bytes:
    """Cadena SASL XOAUTH2 lista para imaplib.authenticate."""
    return f"user={correo}\x01auth=Bearer {token}\x01\x01".encode()


# ---------- GOOGLE ----------
def _google_client_config():
    ajustes = _ajustes_oauth()
    if not ajustes["google_client_id"] or not ajustes["google_client_secret"]:
        raise RuntimeError(
            "Falta el Client ID/Secret de Google (Google Cloud Console -> "
            "Credenciales -> ID de cliente OAuth -> App de escritorio). "
            "Configúrelos en Correos -> Paso 0."
        )
    return {
        "installed": {
            "client_id": ajustes["google_client_id"],
            "client_secret": ajustes["google_client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _google_login(correo):
    if InstalledAppFlow is None:
        raise RuntimeError("Falta google-auth-oauthlib: pip install google-auth-oauthlib")
    if keyring is None:
        raise RuntimeError("Falta keyring: pip install keyring")
    # Abre el navegador con el login oficial de Google.
    flow = InstalledAppFlow.from_client_config(_google_client_config(), GOOGLE_SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    keyring.set_password(APP, correo, creds.to_json())
    return creds


def _google_token(correo):
    if Credentials is None or Request is None or keyring is None:
        raise RuntimeError("Faltan dependencias OAuth de Google o keyring.")
    datos = keyring.get_password(APP, correo)
    if not datos:
        raise RuntimeError("Sin sesion de Google: vuelva a conectar la cuenta.")
    creds = Credentials.from_authorized_user_info(json.loads(datos), GOOGLE_SCOPES)
    if not creds.valid:
        creds.refresh(Request())  # renueva con el refresh token, sin login
        keyring.set_password(APP, correo, creds.to_json())
    return creds.token


# ---------- MICROSOFT ----------
def _ms_client_id():
    client_id = _ajustes_oauth()["microsoft_client_id"]
    if not client_id:
        raise RuntimeError(
            "Falta el Client ID de Microsoft (Entra -> Registro de aplicaciones). "
            "Configúrelo en Correos -> Paso 0."
        )
    return client_id


def _ms_app(cache):
    if msal is None:
        raise RuntimeError("Falta msal: pip install msal")
    return msal.PublicClientApplication(_ms_client_id(), authority=MS_AUTHORITY,
                                        token_cache=cache)


def _ms_login(correo):
    if keyring is None:
        raise RuntimeError("Falta keyring: pip install keyring")
    cache = msal.SerializableTokenCache()
    app = _ms_app(cache)
    # Abre el navegador con el login oficial de Microsoft.
    res = app.acquire_token_interactive(MS_SCOPES, login_hint=correo)
    if "access_token" not in res:
        raise RuntimeError(res.get("error_description", "Fallo la autenticacion con Microsoft"))
    keyring.set_password(APP, correo, cache.serialize())
    return res["access_token"]


def _ms_token(correo):
    if keyring is None:
        raise RuntimeError("Falta keyring: pip install keyring")
    datos = keyring.get_password(APP, correo)
    if not datos:
        raise RuntimeError("Sin sesion de Microsoft: vuelva a conectar la cuenta.")
    cache = msal.SerializableTokenCache()
    cache.deserialize(datos)
    app = _ms_app(cache)
    cuentas = app.get_accounts()
    res = app.acquire_token_silent(MS_SCOPES, account=cuentas[0]) if cuentas else None
    if not res or "access_token" not in res:
        return _ms_login(correo)  # el refresh token vencio: pedir login otra vez
    if cache.has_state_changed:
        keyring.set_password(APP, correo, cache.serialize())
    return res["access_token"]


# ---------- API PUBLICA ----------
def obtener_token(correo, auth):
    """Access token fresco (renovacion silenciosa). Lanza si hay que reconectar."""
    if auth == "google":
        return _google_token(correo)
    if auth == "microsoft":
        return _ms_token(correo)
    raise ValueError(f"auth no-OAuth: {auth}")


def conectar(correo, auth, host, puerto=993, token=None):
    """Conexion IMAP autenticada (XOAUTH2 para OAuth). Retorna el IMAP4_SSL."""
    conexion = imaplib.IMAP4_SSL(host, puerto)
    if auth in ("google", "microsoft"):
        token = token if token is not None else obtener_token(correo, auth)
        conexion.authenticate("XOAUTH2", lambda _: xoauth2_string(correo, token))
    return conexion


def _verificar(cuenta):
    """Prueba la conexion antes de dar por buena la cuenta."""
    if cuenta["auth"] == "password":
        conexion = imaplib.IMAP4_SSL(cuenta["host"], cuenta["puerto"])
        conexion.login(cuenta["correo"], cuenta["contrasena"])
    else:
        conexion = conectar(cuenta["correo"], cuenta["auth"],
                            cuenta["host"], cuenta["puerto"])
    conexion.logout()


def registrar_cuenta(correo, contrasena=None, host=None, puerto=993, forzar_microsoft=False):
    """
    Boton "Conectar".
    - Gmail/Outlook: no necesita contrasena, abre el navegador oficial.
    - Dominio custom: requiere contrasena (y host si no es imap.dominio).
    - forzar_microsoft=True para dominios propios alojados en Microsoft 365.
    Devuelve el dict de la cuenta para guardarlo en la BD.
    """
    correo = (correo or "").strip()
    if "@" not in correo:
        raise ValueError("Correo inválido.")
    auth, host_def = detectar_proveedor(correo, forzar_microsoft)
    cuenta = {"correo": correo, "auth": auth, "host": host or host_def,
              "puerto": puerto}

    if auth == "google":
        _google_login(correo)
    elif auth == "microsoft":
        _ms_login(correo)
    else:
        if not (contrasena or "").strip():
            raise ValueError("Este dominio requiere contraseña.")
        cuenta["contrasena"] = contrasena

    _verificar(cuenta)  # prueba la conexion antes de dar por buena la cuenta
    return cuenta


def olvidar(correo):
    """Borra los secretos OAuth de keyring. Mejor esfuerzo: nunca lanza."""
    try:
        if keyring is not None and keyring.get_password(APP, correo):
            keyring.delete_password(APP, correo)
    except Exception:
        pass
