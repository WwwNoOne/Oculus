"""Pruebas del pipeline: deduplicacion por BD, flujo lineal PDF->IA y entrega.

Usan tmp_path y monkeypatch de las constantes de config: nunca tocan
los datos reales del usuario.
"""
import json
from pathlib import Path

import pytest

import src.backend.api as api_mod
from src.backend.database.db_manager import DBManager
from src.backend.services import dte_service as dte_mod
from src.backend.services import excel_service as xl_mod
from src.backend.services.dte_service import DTEService
from src.backend.services.excel_service import ExcelService


def _doc_valido(codigo="CODE-1", tipo="03", fecha="2026-05-10"):
    return {
        "identificacion": {
            "codigoGeneracion": codigo,
            "tipoDte": tipo,
            "numeroControl": "DTE-03-00000000-000000000000000",
            "fecEmi": fecha,
        },
        "emisor": {"nombre": "Proveedor Demo", "nit": "1234-567890-123-4", "nrc": "123456"},
        "resumen": {"totalGravada": 100.0, "subTotal": 100.0, "tributos": []},
    }


def _escribir_json(path: Path, codigo: str, tipo="03", fecha="2026-05-10"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_doc_valido(codigo, tipo, fecha)), encoding="utf-8")


@pytest.fixture()
def carpetas(tmp_path, monkeypatch):
    proc = tmp_path / "02_Procesados"
    otros = tmp_path / "03_Otros_DTEs"
    duplis = tmp_path / "08_Duplicados"
    errores = tmp_path / "09_Errores"
    for carpeta in (proc, otros, duplis, errores):
        carpeta.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(dte_mod, "CARPETA_PROCESADOS", proc)
    monkeypatch.setattr(dte_mod, "CARPETA_OTROS_DTES", otros)
    monkeypatch.setattr(dte_mod, "CARPETA_DUPLICADOS", duplis)
    monkeypatch.setattr(dte_mod, "CARPETA_ERRORES", errores)
    monkeypatch.setattr(xl_mod, "CARPETA_PROCESADOS", proc)
    monkeypatch.setattr(xl_mod, "CARPETA_ERRORES", errores)
    monkeypatch.setattr(api_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api_mod, "CARPETA_PROCESADOS", proc)
    monkeypatch.setattr(api_mod, "CARPETA_OTROS_DTES", otros)
    monkeypatch.setattr(api_mod, "CARPETA_DUPLICADOS", duplis)
    monkeypatch.setattr(api_mod, "CARPETA_ERRORES", errores)
    return {
        "proc": proc, "otros": otros,
        "duplis": duplis, "errores": errores,
    }


@pytest.fixture()
def basedatos(tmp_path, monkeypatch):
    db = DBManager(tmp_path / "test.db")
    monkeypatch.setattr(dte_mod, "db", db)
    monkeypatch.setattr(api_mod, "db", db)
    monkeypatch.setattr(xl_mod, "db", db)
    return db


def _api():
    return api_mod.Api.__new__(api_mod.Api)


def test_es_duplicado_por_bd(carpetas, basedatos):
    svc = DTEService.__new__(DTEService)
    assert svc._es_duplicado(_doc_valido("ABC-123")) is False
    basedatos.dte_upsert("Demo", "2026-05", "ABC-123", "03", "2026-05-10", "", "", "{}")
    assert svc._es_duplicado({"identificacion": {"codigoGeneracion": "  abc-123 "}}) is True
    assert svc._es_duplicado(_doc_valido("OTRO-COD")) is False
    assert svc._es_duplicado({"identificacion": {}}) is False
    assert svc._es_duplicado(None) is False


def test_mover_sin_sobrescribir_no_sobrescribe(tmp_path):
    svc = DTEService.__new__(DTEService)
    origen = tmp_path / "origen"
    destino = tmp_path / "destino"
    origen.mkdir()
    destino.mkdir()
    (destino / "doc.json").write_text('{"a": 1}', encoding="utf-8")
    nuevo = origen / "doc.json"
    nuevo.write_text('{"b": 2}', encoding="utf-8")

    resultado = svc._mover_sin_sobrescribir(nuevo, destino)

    assert resultado.name == "doc_1.json"
    assert resultado.exists()
    assert not nuevo.exists()
    assert (destino / "doc.json").read_text(encoding="utf-8") == '{"a": 1}'


def test_caso2_ia_ok_pdf_a_procesados(tmp_path, carpetas, basedatos):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "PINELI_9_01032025_a.pdf").write_bytes(b"%PDF-1.4 falso")
    _escribir_json(staging / "PINELI_9_01032025_a.json", "C1", fecha="2026-05-10")

    svc = DTEService()
    svc.ocr.process_pdf_to_raw_json = lambda _p: _doc_valido("C1", fecha="2026-05-10")
    res = svc.process_downloads(source_dir=staging)

    assert res["procesados_json"] == 1
    assert res["errores"] == 0
    assert [p for p in staging.iterdir() if p.is_file()] == []
    destino = carpetas["proc"] / "PINELI" / "2026-05"
    assert (destino / "PINELI_9_01032025_a.pdf").is_file()
    filas = basedatos.get_dte_rows("PINELI", "2026-05")
    assert len(filas) == 1
    assert filas[0]["pdf_name"] == "PINELI_9_01032025_a.pdf"


def test_caso2_ia_ok_huerfano_origen_ia(tmp_path, carpetas, basedatos):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "PINELI_9_01032025_solo.pdf").write_bytes(b"%PDF-1.4 falso")
    # JSON oficial corrupto: la IA decide.
    (staging / "PINELI_9_01032025_solo.json").write_text("{roto", encoding="utf-8")

    svc = DTEService()
    svc.ocr.process_pdf_to_raw_json = lambda _p: _doc_valido("C9", fecha="2026-05-10")
    res = svc.process_downloads(source_dir=staging)

    assert res["procesados_ocr"] == 1
    assert (carpetas["proc"] / "PINELI" / "2026-05" / "PINELI_9_01032025_solo.pdf").is_file()
    assert len(basedatos.get_dte_rows("PINELI", "2026-05")) == 1
    assert [p for p in staging.iterdir() if p.is_file()] == []


def test_caso1_ia_falla_pdf_a_errores(tmp_path, carpetas, basedatos):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "PINELI_9_01032025_solo.pdf").write_bytes(b"%PDF-1.4 falso")

    svc = DTEService()
    svc.ocr.process_pdf_to_raw_json = lambda _p: None  # sin datos
    res = svc.process_downloads(source_dir=staging)

    assert res["errores"] == 1
    assert [p for p in staging.iterdir() if p.is_file()] == []
    destino = carpetas["errores"] / "PINELI" / "2025-03"
    assert (destino / "PINELI_9_01032025_solo.pdf").is_file()
    assert basedatos.count_dte_rows("PINELI", "2025-03") == 0


def test_duplicado_por_bd_va_a_duplicados(tmp_path, carpetas, basedatos):
    basedatos.dte_upsert("PINELI", "2026-05", "C1", "03", "2026-05-10", "", "viejo.pdf", "{}")
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "PINELI_9_01032025_a.pdf").write_bytes(b"%PDF-1.4 falso")
    _escribir_json(staging / "PINELI_9_01032025_a.json", "C1", fecha="2026-05-10")

    svc = DTEService()
    svc.ocr.process_pdf_to_raw_json = lambda _p: _doc_valido("C1", fecha="2026-05-10")
    res = svc.process_downloads(source_dir=staging)

    assert res["duplicados"] == 1
    destino = carpetas["duplis"] / "PINELI" / "2026-05"
    assert sum(1 for p in destino.iterdir() if p.is_file()) == 2
    assert basedatos.count_dte_rows("PINELI", "2026-05") == 1


def test_flujo_lineal_par_fallido_a_errores(tmp_path, carpetas, basedatos):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "PINELI_9_01032025_doc.pdf").write_bytes(b"%PDF-1.4 falso")
    (staging / "PINELI_9_01032025_roto.json").write_text("{no es json", encoding="utf-8")

    svc = DTEService()
    svc.ocr.process_pdf_to_raw_json = lambda _p: None
    res = svc.process_downloads(source_dir=staging)

    # El PDF y el JSON comparten UID: fallan como un solo documento.
    assert res["errores"] == 1
    assert [p for p in staging.iterdir() if p.is_file()] == []
    destino = carpetas["errores"] / "PINELI" / "2025-03"
    assert sum(1 for p in destino.iterdir() if p.is_file()) == 2


@pytest.mark.parametrize("alias", ["../x", "..", "a/b", "a\\b", "", "   "])
def test_delete_client_data_rechaza_alias_invalido(tmp_path, carpetas, basedatos, alias):
    ok, _msg = _api().delete_client_data(alias, confirm=True)
    assert ok is False


def test_delete_client_data_exige_confirmacion(carpetas, basedatos):
    ok, _msg = _api().delete_client_data("RP1", confirm=False)
    assert ok is False


def test_delete_client_data_rechaza_normal_sin_force(carpetas, basedatos):
    basedatos.set_company_kind("Normal", "normal")
    objetivo = carpetas["proc"] / "Normal"
    objetivo.mkdir()
    (objetivo / "f.pdf").write_bytes(b"x")

    ok, _msg = _api().delete_client_data("Normal", confirm=True, force=False)

    assert ok is False
    assert objetivo.exists()


def test_delete_client_data_elimina_recovery_sin_tocar_correos(tmp_path, carpetas, basedatos):
    basedatos.set_company_kind("RP1", "recovery")
    basedatos.add_email("EmpresaX", "cuenta@empresa.com", "secreto", "imap.gmail.com", 993)
    for key in ("proc", "otros", "duplis", "errores"):
        destino = carpetas[key] / "RP1"
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "f.pdf").write_bytes(b"x")
    legado = tmp_path / "05_Respaldo_PDF" / "RP1"
    legado.mkdir(parents=True, exist_ok=True)
    (legado / "viejo.pdf").write_bytes(b"x")

    ok, msg = _api().delete_client_data("RP1", confirm=True, force=False)

    assert ok is True
    assert "5 archivos" in msg
    for key in ("proc", "otros", "duplis", "errores"):
        assert not (carpetas[key] / "RP1").exists()
    assert not legado.exists()
    assert basedatos.get_company_kind("RP1") is None
    assert len(basedatos.get_all_emails()) == 1


def test_carpeta_de_entrega_con_pdf_y_errores(tmp_path, carpetas, basedatos):
    pdf_dir = carpetas["proc"] / "Demo" / "2026-05"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    (pdf_dir / "factura1.pdf").write_bytes(b"%PDF-1.4 falso")
    basedatos.dte_upsert("Demo", "2026-05", "CODE-1", "03", "2026-05-10",
                         "DTE-03-X", "factura1.pdf", json.dumps(_doc_valido("CODE-1")))
    basedatos.dte_upsert("Demo", "2026-05", "CODE-2", "03", "2026-05-11",
                         "DTE-03-Y", "", json.dumps(_doc_valido("CODE-2", fecha="2026-05-11")))
    err = carpetas["errores"] / "Demo" / "2026-05"
    err.mkdir(parents=True, exist_ok=True)
    (err / "malo.pdf").write_bytes(b"x")

    xl = ExcelService()
    ok, msg, export = xl.generar_libro_compras(
        carpetas["proc"] / "Demo", "2026-05", str(tmp_path / "entregas")
    )

    assert ok is True
    delivery = Path(export)
    assert delivery.name == "Demo_2026-05"
    assert list(delivery.glob("*.xlsx"))
    assert len(list((delivery / "JSON").glob("*.json"))) == 2
    assert len(list((delivery / "PDF").glob("*.pdf"))) == 1
    assert len(list((delivery / "Errores").glob("*"))) == 1
    assert "Documentos exportados: 2" in msg
    assert "1 sin PDF" in msg
    assert "1 con errores" in msg


def test_diagnostics_cuenta_documentos_y_errores(carpetas, basedatos):
    pdf_dir = carpetas["proc"] / "Demo" / "2026-05"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    (pdf_dir / "a.pdf").write_bytes(b"x")
    basedatos.dte_upsert("Demo", "2026-05", "C1", "03", "2026-05-10", "", "a.pdf", "{}")
    err = carpetas["errores"] / "Demo" / "2026-05"
    err.mkdir(parents=True, exist_ok=True)
    (err / "malo.pdf").write_bytes(b"x")

    d = _api().get_excel_diagnostics("Demo", "2026-05")

    assert d["json_count"] == 1
    assert d["pdf_count"] == 1
    assert d["error_count"] == 1


def test_crypto_descarta_fernet_antiguo_sin_clave():
    from src.backend.utils.crypto import decrypt_data, encrypt_data

    # Tokens Fernet de compilaciones anteriores (clave desconocida) no deben
    # usarse como API key: se descartan con "".
    assert decrypt_data("gAAAAABonauthentictokenimposiblededescifrar") == ""
    # Round-trip del esquema actual.
    assert decrypt_data(encrypt_data("llx-clave-secreta")) == "llx-clave-secreta"
    assert decrypt_data("") == ""


def test_llamaparse_principal_sin_clave_no_hace_red(tmp_path):
    from src.backend.services.ocr_service import OCRService

    ocr = OCRService.__new__(OCRService)
    ocr.llamaparse_api_key = ""
    pdf = tmp_path / "vacio.pdf"
    pdf.write_bytes(b"%PDF-1.4 falso")
    assert ocr._extraer_estructurado_llamaparse(str(pdf)) is None


def test_llamaparse_sin_credito_pasa_a_pago():
    from src.backend.services.ocr_service import OCRService

    assert OCRService._es_falta_credito(Exception("402 Payment Required: quota exceeded")) is True
    assert OCRService._es_falta_credito(Exception("rate limit 429 exceeded")) is True
    assert OCRService._es_falta_credito(Exception("timeout de red")) is False


def test_fecha_emision_valida_mata_fechas_absurdas():
    from src.backend.utils.json_utils import fecha_emision_valida

    assert fecha_emision_valida("2026-05-10") is True
    assert fecha_emision_valida("2000-00-00") is False
    assert fecha_emision_valida("2026-13-01") is False
    assert fecha_emision_valida("2026-02-30") is False
    assert fecha_emision_valida("") is False
    assert fecha_emision_valida(None) is False


def test_excel_omite_fecha_invalida():
    from src.backend.services.excel_service import ExcelService

    xl = ExcelService()
    data = _doc_valido("CX", fecha="2000-00-00")
    row, _codigo = xl._fila_desde_data(data, 1)
    assert row is None


def test_db_auth_type_roundtrip(tmp_path):
    from src.backend.database.db_manager import DBManager

    db = DBManager(tmp_path / "a.db")
    ok, _ = db.add_email("Emp", "a@gmail.com", "", "imap.gmail.com", 993, "2026-05-01", "google")
    assert ok
    assert db.get_all_emails()[0]["auth_type"] == "google"
    db.update_email("a@gmail.com", "Emp", "a@gmail.com", "", "imap.gmail.com", 993, "2026-05-01", "microsoft")
    assert db.get_all_emails()[0]["auth_type"] == "microsoft"
    db.update_email("a@gmail.com", "Emp", "a@gmail.com", "", "imap.gmail.com", 993)
    assert db.get_all_emails()[0]["auth_type"] == "microsoft"


def test_api_add_email_oauth_sin_password(carpetas, basedatos):
    api = _api()
    ok, _ = api.add_email("Emp", "a@gmail.com", "", "imap.gmail.com", 993, "2026-05-01", "google")
    assert ok
    ok, _ = api.add_email("Emp", "b@gmail.com", "", "imap.gmail.com", 993)
    assert not ok


def test_email_oauth_descarga_adjuntos(tmp_path, monkeypatch):
    import email as email_lib
    from email.message import EmailMessage
    from src.backend.services.email_service import EmailService

    msg = EmailMessage()
    msg["Subject"] = "DTE prueba"
    msg["From"] = "x@y.com"
    msg["Date"] = email_lib.utils.formatdate()
    msg.add_attachment(b"%PDF-1.4 falso", maintype="application",
                       subtype="pdf", filename="doc.pdf")
    crudo = msg.as_bytes()

    class FakeIMAP:
        def __init__(self, host, port):
            pass

        def authenticate(self, mech, func):
            assert mech == "XOAUTH2"
            assert func(None).startswith(b"user=cuenta@test.com\x01")

        def select(self, *a, **k):
            return ("OK", [b"1"])

        def uid(self, cmd, *args):
            if cmd == "search":
                return ("OK", [b"101"])
            if cmd == "fetch":
                return ("OK", [(b"101 (RFC822 {5}", crudo)])
            raise AssertionError(cmd)

        def logout(self):
            pass

    monkeypatch.setattr("imaplib.IMAP4_SSL", FakeIMAP)
    dest = tmp_path / "down"
    dest.mkdir()
    otros = tmp_path / "otros"
    otros.mkdir()
    svc = EmailService(str(dest), str(otros))
    res = svc.descargar_correos("TEST", "imap.gmail.com", 993, "cuenta@test.com", "",
                                auth_type="google", oauth_token="TOK",
                                estado_key="cuenta@test.com", start_date="2026-01-01")
    assert res["descargados"] == 1
    assert len(list(dest.glob("TEST_101_*_doc.pdf"))) == 1
    import json as _json
    estado = _json.loads((dest / "sync_estado.json").read_text())
    assert "101" in estado["cuenta@test.com"]


def test_get_data_dir_respeta_override(monkeypatch, tmp_path):
    from src.backend.utils import config as config_mod

    monkeypatch.setenv("OCULUS_DATA_DIR", str(tmp_path / "workspace"))
    assert config_mod.get_data_dir() == tmp_path / "workspace"
    monkeypatch.delenv("OCULUS_DATA_DIR", raising=False)
    default = config_mod.get_data_dir()
    assert isinstance(default, Path)
    assert default.name in {"data", "Oculus_Workspace"}


def test_pdf_sin_ia_retorna_none_sin_contaminar():
    from src.backend.services.ocr_service import OCRService

    ocr = OCRService.__new__(OCRService)
    ocr.deepseek_api_key = ""
    ocr.gemini_api_key = ""
    ocr.llamaparse_api_key = ""
    ocr._extract_local_text = lambda _p: "texto con mas de cincuenta caracteres para pasar el umbral......"
    assert ocr.process_pdf_to_raw_json("cualquiera.pdf") is None


def test_json_malformado_sin_ia_retorna_none():
    from src.backend.services.ocr_service import OCRService

    ocr = OCRService.__new__(OCRService)
    ocr.deepseek_api_key = ""
    ocr.gemini_api_key = ""
    ocr.llamaparse_api_key = ""
    assert ocr.process_raw_json_text("{no es json") is None
    assert ocr.process_raw_json_text("") is None


def test_oauth_detectar_proveedor():
    from src.backend.services import oauth_service as oauth

    assert oauth.detectar_proveedor("a@gmail.com") == ("google", "imap.gmail.com")
    assert oauth.detectar_proveedor("a@googlemail.com") == ("google", "imap.gmail.com")
    assert oauth.detectar_proveedor("a@outlook.com") == ("microsoft", "outlook.office365.com")
    assert oauth.detectar_proveedor("a@hotmail.com") == ("microsoft", "outlook.office365.com")
    assert oauth.detectar_proveedor("facturas@foodservices.com") == ("password", "imap.foodservices.com")
    assert oauth.detectar_proveedor("facturas@foodservices.com", forzar_microsoft=True) == (
        "microsoft", "outlook.office365.com")


def test_oauth_xoauth2_formato():
    from src.backend.services import oauth_service as oauth

    cadena = oauth.xoauth2_string("a@gmail.com", "TOKEN123")
    assert cadena == b"user=a@gmail.com\x01auth=Bearer TOKEN123\x01\x01"


def test_oauth_registrar_password_verifica_conexion(monkeypatch):
    from src.backend.services import oauth_service as oauth

    vistos = {}

    class FakeKeyring:
        def set_password(self, app, correo, valor):
            vistos[correo] = valor

    monkeypatch.setattr(oauth, "keyring", FakeKeyring())
    monkeypatch.setattr(oauth, "_verificar", lambda cuenta: vistos.update(verificada=True))
    cuenta = oauth.registrar_cuenta("facturas@foodservices.com", contrasena="secreto",
                                    host="mail.foodservices.com")
    assert cuenta == {"correo": "facturas@foodservices.com", "auth": "password",
                      "host": "mail.foodservices.com", "puerto": 993,
                      "contrasena": "secreto"}
    import pytest as _pytest
    with _pytest.raises(ValueError):
        oauth.registrar_cuenta("x@dominio.com")


def test_oauth_google_token_refresh(monkeypatch):
    from src.backend.services import oauth_service as oauth

    almacen = {"a@gmail.com": '{"token": "viejo", "refresh_token": "r"}'}

    class FakeKeyring:
        def get_password(self, app, correo):
            return almacen.get(correo)

        def set_password(self, app, correo, valor):
            almacen[correo] = valor

    class FakeCreds:
        valid = False
        token = "nuevo-token"

        def refresh(self, _req):
            self.token = "nuevo-token"

        def to_json(self):
            return '{"token": "nuevo-token"}'

    monkeypatch.setattr(oauth, "keyring", FakeKeyring())
    monkeypatch.setattr(oauth, "Credentials",
                        type("C", (), {"from_authorized_user_info": staticmethod(lambda *a: FakeCreds())}))
    monkeypatch.setattr(oauth, "Request", type("R", (), {}))
    assert oauth.obtener_token("a@gmail.com", "google") == "nuevo-token"
    assert "nuevo-token" in almacen["a@gmail.com"]
