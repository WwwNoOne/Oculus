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
    for carpeta in (proc, otros, pdfs, respaldo, duplis):
        carpeta.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(dte_mod, "CARPETA_PROCESADOS", proc)
    monkeypatch.setattr(dte_mod, "CARPETA_OTROS_DTES", otros)
    monkeypatch.setattr(dte_mod, "CARPETA_DUPLICADOS", duplis)
    monkeypatch.setattr(xl_mod, "CARPETA_RESPALDO_PDF", pdfs)
    monkeypatch.setattr(api_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api_mod, "CARPETA_PROCESADOS", proc)
    monkeypatch.setattr(api_mod, "CARPETA_OTROS_DTES", otros)
    monkeypatch.setattr(api_mod, "CARPETA_RESPALDO_PDF", pdfs)
    monkeypatch.setattr(api_mod, "CARPETA_DESCARGAS_RESPALDO", respaldo)
    monkeypatch.setattr(api_mod, "CARPETA_DUPLICADOS", duplis)
    return {
        "proc": proc, "otros": otros, "pdfs": pdfs,
        "respaldo": respaldo, "duplis": duplis,
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
