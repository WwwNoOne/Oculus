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
    respaldo = tmp_path / "07_Descargas_Respaldo"
    duplis = tmp_path / "08_Duplicados"
    errores = tmp_path / "09_Errores"
    for carpeta in (proc, otros, respaldo, duplis, errores):
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
    monkeypatch.setattr(api_mod, "CARPETA_DESCARGAS_RESPALDO", respaldo)
    monkeypatch.setattr(api_mod, "CARPETA_DUPLICADOS", duplis)
    monkeypatch.setattr(api_mod, "CARPETA_ERRORES", errores)
    return {
        "proc": proc, "otros": otros,
        "respaldo": respaldo, "duplis": duplis, "errores": errores,
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
    for key in ("proc", "otros", "respaldo", "duplis", "errores"):
        destino = carpetas[key] / "RP1"
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "f.pdf").write_bytes(b"x")
    legado = tmp_path / "05_Respaldo_PDF" / "RP1"
    legado.mkdir(parents=True, exist_ok=True)
    (legado / "viejo.pdf").write_bytes(b"x")

    ok, msg = _api().delete_client_data("RP1", confirm=True, force=False)

    assert ok is True
    assert "6 archivos" in msg
    for key in ("proc", "otros", "respaldo", "duplis", "errores"):
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


def test_llamaparse_sin_clave_no_hace_red(tmp_path):
    from src.backend.services.ocr_service import OCRService

    ocr = OCRService.__new__(OCRService)
    ocr.llamaparse_api_key = ""
    pdf = tmp_path / "vacio.pdf"
    pdf.write_bytes(b"%PDF-1.4 falso")
    assert ocr._extract_with_llamaparse(str(pdf)) == ""


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
