"""Pruebas de deduplicación, borrado seguro y carpeta de entrega (Bloques A-C).

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


def _escribir_json(path: Path, codigo: str, tipo="03", fecha="2026-05-10"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "identificacion": {
            "codigoGeneracion": codigo,
            "tipoDte": tipo,
            "numeroControl": "DTE-03-00000000-000000000000000",
            "fecEmi": fecha,
        },
        "emisor": {"nombre": "Proveedor Demo", "nit": "1234-567890-123-4", "nrc": "123456"},
        "resumen": {"totalGravada": 100.0, "subTotal": 100.0, "tributos": []},
    }), encoding="utf-8")


@pytest.fixture()
def carpetas(tmp_path, monkeypatch):
    proc = tmp_path / "02_Procesados"
    otros = tmp_path / "03_Otros_DTEs"
    pdfs = tmp_path / "05_Respaldo_PDF"
    respaldo = tmp_path / "07_Descargas_Respaldo"
    duplis = tmp_path / "08_Duplicados"
    errores = tmp_path / "09_Errores"
    for carpeta in (proc, otros, pdfs, respaldo, duplis, errores):
        carpeta.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(dte_mod, "CARPETA_PROCESADOS", proc)
    monkeypatch.setattr(dte_mod, "CARPETA_OTROS_DTES", otros)
    monkeypatch.setattr(dte_mod, "CARPETA_DUPLICADOS", duplis)
    monkeypatch.setattr(dte_mod, "CARPETA_ERRORES", errores)
    monkeypatch.setattr(xl_mod, "CARPETA_RESPALDO_PDF", pdfs)
    monkeypatch.setattr(api_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api_mod, "CARPETA_PROCESADOS", proc)
    monkeypatch.setattr(api_mod, "CARPETA_OTROS_DTES", otros)
    monkeypatch.setattr(api_mod, "CARPETA_RESPALDO_PDF", pdfs)
    monkeypatch.setattr(api_mod, "CARPETA_DESCARGAS_RESPALDO", respaldo)
    monkeypatch.setattr(api_mod, "CARPETA_DUPLICADOS", duplis)
    monkeypatch.setattr(api_mod, "CARPETA_ERRORES", errores)
    return {
        "proc": proc, "otros": otros, "pdfs": pdfs,
        "respaldo": respaldo, "duplis": duplis, "errores": errores,
    }


def _api_con_db_aislada(tmp_path, monkeypatch):
    db = DBManager(tmp_path / "test.db")
    monkeypatch.setattr(api_mod, "db", db)
    return api_mod.Api.__new__(api_mod.Api), db


def test_es_duplicado_detecta_codigo_existente(carpetas):
    svc = DTEService.__new__(DTEService)
    _escribir_json(carpetas["proc"] / "Demo" / "2026-05" / "doc1.json", "ABC-123")
    _escribir_json(carpetas["otros"] / "Demo" / "2026-05" / "otro.json", "ZZZ-9")

    assert svc._es_duplicado({"identificacion": {"codigoGeneracion": "  abc-123 "}}, "Demo/2026-05") is True
    assert svc._es_duplicado({"identificacion": {"codigoGeneracion": "zzz-9"}}, "Demo/2026-05") is True
    assert svc._es_duplicado({"identificacion": {"codigoGeneracion": "NO-EXISTE"}}, "Demo/2026-05") is False
    assert svc._es_duplicado({"identificacion": {"codigoGeneracion": "ABC-123"}}, "Demo/2026-06") is False
    assert svc._es_duplicado({"identificacion": {}}, "Demo/2026-05") is False
    assert svc._es_duplicado(None, "Demo/2026-05") is False


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


@pytest.mark.parametrize("alias", ["../x", "..", "a/b", "a\\b", "", "   "])
def test_delete_client_data_rechaza_alias_invalido(tmp_path, monkeypatch, carpetas, alias):
    api, _db = _api_con_db_aislada(tmp_path, monkeypatch)
    ok, _msg = api.delete_client_data(alias, confirm=True)
    assert ok is False


def test_delete_client_data_exige_confirmacion(tmp_path, monkeypatch, carpetas):
    api, _db = _api_con_db_aislada(tmp_path, monkeypatch)
    ok, _msg = api.delete_client_data("RP1", confirm=False)
    assert ok is False


def test_delete_client_data_rechaza_normal_sin_force(tmp_path, monkeypatch, carpetas):
    api, db = _api_con_db_aislada(tmp_path, monkeypatch)
    db.set_company_kind("Normal", "normal")
    objetivo = carpetas["proc"] / "Normal"
    objetivo.mkdir()
    (objetivo / "f.json").write_text("{}", encoding="utf-8")

    ok, _msg = api.delete_client_data("Normal", confirm=True, force=False)

    assert ok is False
    assert objetivo.exists()


def test_delete_client_data_elimina_recovery_sin_tocar_correos(tmp_path, monkeypatch, carpetas):
    api, db = _api_con_db_aislada(tmp_path, monkeypatch)
    db.set_company_kind("RP1", "recovery")
    db.add_email("EmpresaX", "cuenta@empresa.com", "secreto", "imap.gmail.com", 993)
    for key in ("proc", "otros", "pdfs", "respaldo", "duplis"):
        destino = carpetas[key] / "RP1"
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "f.json").write_text("{}", encoding="utf-8")

    ok, msg = api.delete_client_data("RP1", confirm=True, force=False)

    assert ok is True
    assert "5 archivos" in msg
    for key in ("proc", "otros", "pdfs", "respaldo", "duplis"):
        assert not (carpetas[key] / "RP1").exists()
    assert db.get_company_kind("RP1") is None
    assert len(db.get_all_emails()) == 1


def test_carpeta_de_entrega_estructura(carpetas, tmp_path):
    xl = ExcelService()
    _escribir_json(carpetas["proc"] / "Demo" / "2026-05" / "factura1.json", "CODE-1")
    _escribir_json(carpetas["proc"] / "Demo" / "2026-05" / "factura2.json", "CODE-2")
    pdf_dir = carpetas["pdfs"] / "Demo" / "2026-05"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    (pdf_dir / "factura1.pdf").write_bytes(b"%PDF-1.4 falso")

    ok, msg, export = xl.generar_libro_compras(
        carpetas["proc"] / "Demo", "2026-05", str(tmp_path / "entregas")
    )

    assert ok is True
    delivery = Path(export)
    assert delivery.name == "Demo_2026-05"
    assert list(delivery.glob("*.xlsx"))
    assert len(list((delivery / "JSON").glob("*.json"))) == 2
    assert len(list((delivery / "PDF").glob("*.pdf"))) == 1
    assert "Documentos exportados: 2" in msg
    assert "1 sin PDF" in msg


def test_excel_no_repite_codigo_generacion(carpetas, tmp_path):
    xl = ExcelService()
    _escribir_json(carpetas["proc"] / "Demo" / "2026-05" / "a.json", "CODE-1")
    _escribir_json(carpetas["proc"] / "Demo" / "2026-05" / "b.json", "code-1")

    ok, msg, export = xl.generar_libro_compras(
        carpetas["proc"] / "Demo", "2026-05", str(tmp_path / "entregas")
    )

    assert ok is True
    assert len(list((Path(export) / "JSON").glob("*.json"))) == 1
    assert "Documentos exportados: 1" in msg


def test_stem_key_ignora_standard_y_sufijos():
    assert ExcelService._stem_key("Doc_standard.json") == "doc"
    assert ExcelService._stem_key("DOC_STANDARD_2.PDF") == "doc"
    assert ExcelService._stem_key("factura_1_2.pdf") == "factura"


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
    import os
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


def test_flujo_lineal_fallos_van_a_errores(tmp_path, monkeypatch, carpetas):
    from src.backend.services.dte_service import DTEService

    monkeypatch.setattr(dte_mod, "db", DBManager(tmp_path / "lineal.db"))
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "PINELI_9_01032025_doc.pdf").write_bytes(b"%PDF-1.4 falso")
    (staging / "PINELI_9_01032025_roto.json").write_text("{no es json", encoding="utf-8")

    svc = DTEService()
    svc.ocr.process_pdf_to_raw_json = lambda _p: None  # sin datos
    res = svc.process_downloads(source_dir=staging)

    # El PDF y el JSON comparten UID: fallan como un solo documento.
    assert res["errores"] == 1
    # Nada se queda en descargas: sin reintentos eternos.
    assert [p for p in staging.iterdir() if p.is_file()] == []
    destino = carpetas["errores"] / "PINELI" / "2025-03"
    assert sum(1 for p in destino.iterdir() if p.is_file()) == 2


def test_flujo_lineal_pdf_huerfano_fallido(tmp_path, monkeypatch, carpetas):
    from src.backend.services.dte_service import DTEService

    monkeypatch.setattr(dte_mod, "db", DBManager(tmp_path / "lineal2.db"))
    staging = tmp_path / "staging2"
    staging.mkdir()
    (staging / "PINELI_7_01032025_solo.pdf").write_bytes(b"%PDF-1.4 falso")
    (staging / "OTRO_8_01032025_roto.json").write_text("{no es json", encoding="utf-8")

    svc = DTEService()
    svc.ocr.process_pdf_to_raw_json = lambda _p: None  # sin datos
    res = svc.process_downloads(source_dir=staging)

    assert res["errores"] == 2
    assert [p for p in staging.iterdir() if p.is_file()] == []
    pineli = carpetas["errores"] / "PINELI" / "2025-03"
    otro = carpetas["errores"] / "OTRO" / "2025-03"
    assert sum(1 for p in pineli.iterdir() if p.is_file()) == 1
    assert sum(1 for p in otro.iterdir() if p.is_file()) == 1


def test_diagnostics_cuenta_errores(tmp_path, monkeypatch, carpetas):
    api, _db = _api_con_db_aislada(tmp_path, monkeypatch)
    (carpetas["proc"] / "Demo" / "2026-05").mkdir(parents=True, exist_ok=True)
    (carpetas["proc"] / "Demo" / "2026-05" / "a.json").write_text("{}", encoding="utf-8")
    err = carpetas["errores"] / "Demo" / "2026-05"
    err.mkdir(parents=True, exist_ok=True)
    (err / "malo.pdf").write_bytes(b"x")

    d = api.get_excel_diagnostics("Demo", "2026-05")

    assert d["json_count"] == 1
    assert d["pdf_count"] == 0
    assert d["error_count"] == 1
