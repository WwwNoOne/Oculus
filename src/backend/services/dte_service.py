import os
import json
import shutil
import re
import datetime
from pathlib import Path
from src.backend.utils.config import DATA_DIR, CARPETA_DESCARGAS, CARPETA_PROCESADOS, CARPETA_OTROS_DTES, CARPETA_DUPLICADOS, CARPETA_ERRORES
from src.backend.database.db_manager import db
from src.backend.services.ocr_service import OCRService
from src.backend.utils.json_utils import extract_identificacion

class DTEService:
    def __init__(self):
        self.ocr = OCRService()
        self.target_codes = ["03", "05", "06", "14"]

    def _leer_json_estandarizado(self, json_path: Path):
        """Lee el texto del JSON y lo estandariza vía IA para evitar errores estructurales."""
        try:
            try:
                texto = json_path.read_text(encoding='utf-8-sig')
            except UnicodeDecodeError:
                texto = json_path.read_text(encoding='latin-1')
            # Pasar por DeepSeek para limpiar y estandarizar
            return self.ocr.process_raw_json_text(texto)
        except Exception as e:
            print(f"Error estandarizando {json_path.name}: {e}")
            return None

    def _get_identificacion(self, data: dict):
        """Obtiene identificacion tanto de DTE directos como de respuestas anidadas."""
        return extract_identificacion(data)

    def _codigo(self, data) -> str:
        """codigoGeneracion normalizado (mayusculas, sin espacios) para deduplicar."""
        if not isinstance(data, dict):
            return ""
        identificacion = self._get_identificacion(data)
        if not isinstance(identificacion, dict):
            return ""
        return str(identificacion.get("codigoGeneracion", "") or "").strip().upper()

    def _es_duplicado(self, data, subfolder: str = "") -> bool:
        """Duplicado si el codigoGeneracion ya tiene fila en BD (ya no hay JSONs en disco)."""
        return db.dte_exists(self._codigo(data))

    def _mover_a_duplicados(self, source_paths: list, subfolder: str):
        """Mueve archivos ya procesados antes a 08_Duplicados/<subfolder> sin borrarlos."""
        target_dir = CARPETA_DUPLICADOS / subfolder
        for sp in source_paths:
            path = Path(sp)
            if path.exists() and path.is_file():
                self._mover_sin_sobrescribir(path, target_dir)

    def _mover_a_errores(self, source_paths: list, subfolder: str):
        """Mueve archivos que no se pudieron procesar a 09_Errores/<subfolder>.

        Garantiza flujo lineal: todo lo que entra a descargas sale exactamente
        una vez (destino, duplicados o errores), sin reintentos eternos.
        """
        target_dir = CARPETA_ERRORES / subfolder
        for sp in source_paths:
            path = Path(sp)
            if path.exists() and path.is_file():
                self._mover_sin_sobrescribir(path, target_dir)

    def _subfolder(self, filename: str, mes_anio: str, destination_alias=None) -> str:
        """Deduce <alias>/<mes> desde el nombre con formato ALIAS_UID_FECHA_..."""
        if destination_alias:
            cliente = destination_alias
        else:
            partes = filename.split('_')
            cliente = partes[0] if len(partes) > 1 else "Cliente_Desconocido"
        cliente_folder = "".join(x for x in cliente if x.isalnum() or x in " -_").strip()
        return f"{cliente_folder}/{mes_anio}"

    def _alias_carpeta(self, filename: str, destination_alias=None) -> str:
        """Solo la parte del alias (para la fila de BD)."""
        if destination_alias:
            cliente = destination_alias
        else:
            partes = filename.split('_')
            cliente = partes[0] if len(partes) > 1 else "Cliente_Desconocido"
        return "".join(x for x in cliente if x.isalnum() or x in " -_").strip() or "Cliente_Desconocido"

    def _tipo_final(self, identificacion) -> str:
        """Tipo DTE final con rescate desde numeroControl. '' si irreconocible."""
        identificacion = identificacion if isinstance(identificacion, dict) else {}
        tipo = str(identificacion.get("tipoDte", "") or "").strip().upper()
        if not re.fullmatch(r"\d{2}", tipo) or tipo == "00":
            control = str(identificacion.get("numeroControl", "") or "").upper()
            for code in self.target_codes:
                if f"DTE-{code}" in control:
                    return code
            return ""
        return tipo

    def _fecha_valida(self, fecha: str) -> bool:
        """Fecha calendario real entre 1990 y 2100 (mata 2000/00/00 y similares)."""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha or ""):
            return False
        try:
            parsed = datetime.datetime.strptime(fecha, "%Y-%m-%d")
        except ValueError:
            return False
        return 1990 <= parsed.year <= 2100

    def _valido(self, data) -> bool:
        """Dato utilizable: codigo + tipo conocido/rescatable + fecha real."""
        if not isinstance(data, dict):
            return False
        identificacion = self._get_identificacion(data)
        if not isinstance(identificacion, dict):
            return False
        if not str(identificacion.get("codigoGeneracion", "") or "").strip():
            return False
        if not self._tipo_final(identificacion):
            return False
        return self._fecha_valida(str(identificacion.get("fecEmi", "") or ""))

    def _emparejar_pdf(self, pdf: Path, jsons_por_uid: dict, jsons_usados: set):
        """Empareja el PDF con su JSON del correo (nombre/codigo o 1-a-1 por UID).

        Retorna (ruta_json | None, datos_estandarizados | None) sin escribir nada.
        """
        uid = self._get_uid_from_filename(pdf.name)
        posibles = [j for j in jsons_por_uid.get(uid, []) if j not in jsons_usados]

        puntuados = sorted(
            ((self._pair_score(pdf.name, j.name), j) for j in posibles),
            key=lambda item: item[0],
            reverse=True,
        )
        elegido = None
        if puntuados and puntuados[0][0] > 0 and (
            len(puntuados) == 1 or puntuados[0][0] > puntuados[1][0]
        ):
            elegido = puntuados[0][1]
        elif len(posibles) == 1:
            # Solo hay un par posible en el correo.
            elegido = posibles[0]
            print(f"[*] Emparejamiento heurístico: {pdf.name} <-> {elegido.name}")

        if elegido is None:
            return None, None
        return elegido, self._leer_json_estandarizado(elegido)

    def _revisar_pdf_con_ia(self, pdf: Path):
        """La IA revisa el PDF. Retorna datos validos o None (caso 1: fallo)."""
        try:
            crudo = self.ocr.process_pdf_to_raw_json(str(pdf))
            if crudo is None:
                return None
            return self.ocr.parse_raw_to_standard(crudo)
        except Exception as e:
            print(f"[!] Revision IA fallo para {pdf.name}: {e}")
            return None

    def _get_month_from_filename(self, filename: str) -> str:
        """Usa la fecha del nombre ALIAS_UID_DDMMYYYY como respaldo."""
        match = re.search(r"_(\d{2})(\d{2})(\d{4})(?:_|\.)", filename)
        if match:
            day, month, year = match.groups()
            return f"{year}-{month}"
        return "sin_fecha"

    def _normalizar_stem(self, filename: str) -> str:
        stem = Path(filename).stem.lower()
        return re.sub(r"(?:_\d+)+$", "", stem)

    def _pair_score(self, pdf_name: str, json_name: str) -> int:
        pdf_stem = self._normalizar_stem(pdf_name)
        json_stem = self._normalizar_stem(json_name)
        if pdf_stem == json_stem:
            return 100
        pdf_tokens = set(re.findall(r"[0-9a-f]{8}-[0-9a-f-]{27,}|dte-[0-9]{2}-[a-z0-9-]+", pdf_stem))
        json_tokens = set(re.findall(r"[0-9a-f]{8}-[0-9a-f-]{27,}|dte-[0-9]{2}-[a-z0-9-]+", json_stem))
        return 50 if pdf_tokens.intersection(json_tokens) else 0

    def _is_ai_garbage(self, data: dict, identificacion: dict, tipo_dte: str) -> bool:
        """Detecta salidas IA defectuosas sin borrar JSON originales validos."""
        metadata = data.get("_metadata", {})
        procesado_ia = (
            isinstance(metadata, dict)
            and metadata.get("estado") == "Procesado con IA"
        )
        if not procesado_ia:
            return False
        if data.get("error"):
            return True
        return tipo_dte in {"00", "UNKNOWN"} and not any(
            identificacion.get(key) for key in ("numeroControl", "codigoGeneracion", "fecEmi")
        )

    def _mover_archivos(self, source_paths: list, dest_folder: Path, subfolder_name: str = None):
        """Mueve una lista de archivos a una carpeta destino, opcionalmente dentro de una subcarpeta (mes/año).

        Usa _mover_sin_sobrescribir para no fallar ni sobrescribir si el nombre ya existe.
        """
        target_dir = dest_folder / subfolder_name if subfolder_name else dest_folder
        for sp in source_paths:
            path = Path(sp)
            if path.exists() and path.is_file():
                self._mover_sin_sobrescribir(path, target_dir)

    def _mover_sin_sobrescribir(self, source_path: Path, dest_folder: Path) -> Path:
        dest_folder.mkdir(parents=True, exist_ok=True)
        destination = dest_folder / source_path.name
        suffix = 1
        while destination.exists():
            destination = dest_folder / f"{source_path.stem}_{suffix}{source_path.suffix}"
            suffix += 1
        shutil.move(str(source_path), str(destination))
        return destination

    def migrate_legacy_documents(self):
        """Migra instalaciones anteriores al modelo actual sin borrar nada.

        - Los PDF del respaldo 05_Respaldo_PDF (y sueltos en 03_) se reubican en
          02_Procesados/<alias>/<mes>/ junto a su documento.
        - Se crean las filas de BD desde los JSON historicos de 02_/03_ y se
          vincula cada PDF hermano (sin IA, sin red).
        - La basura de IA antigua se elimina.
        """
        migrated = {"pdf_migrated": 0, "db_backfilled": 0, "ai_deleted": 0}
        legado_pdf = DATA_DIR / "05_Respaldo_PDF"

        for base in (legado_pdf, CARPETA_OTROS_DTES):
            if not base.exists():
                continue
            for path in sorted(p for p in base.rglob("*.pdf") if p.is_file()):
                relative = path.relative_to(base)
                alias = relative.parts[0] if relative.parts else "Cliente_Desconocido"
                periodo = relative.parts[1] if len(relative.parts) > 1 else self._get_month_from_filename(path.name)
                mejor = self._periodo_de_hermano(path)
                if mejor:
                    periodo = mejor
                self._mover_sin_sobrescribir(path, CARPETA_PROCESADOS / alias / periodo)
                migrated["pdf_migrated"] += 1

        # PDFs mas profundos dentro de 02_: subirlos a <alias>/<mes>/.
        if CARPETA_PROCESADOS.exists():
            for path in sorted(p for p in CARPETA_PROCESADOS.rglob("*.pdf") if p.is_file()):
                relative = path.relative_to(CARPETA_PROCESADOS)
                if len(relative.parts) > 3:
                    self._mover_sin_sobrescribir(
                        path, CARPETA_PROCESADOS / relative.parts[0] / relative.parts[1]
                    )
                    migrated["pdf_migrated"] += 1

        # Basura de IA antigua.
        for base in (CARPETA_PROCESADOS, CARPETA_OTROS_DTES):
            if not base.exists():
                continue
            for path in sorted(p for p in base.rglob("*.json") if p.is_file()):
                if path.name.lower().endswith("_estado.json"):
                    continue
                try:
                    try:
                        data = json.loads(path.read_text(encoding="utf-8-sig"))
                    except UnicodeDecodeError:
                        data = json.loads(path.read_text(encoding="latin-1"))
                except Exception:
                    continue
                identificacion = self._get_identificacion(data)
                if self._is_ai_garbage(data, identificacion, self._tipo_final(identificacion)):
                    path.unlink(missing_ok=True)
                    migrated["ai_deleted"] += 1

        migrated["db_backfilled"] = self.backfill_db_from_jsons()

        if any(migrated.values()):
            print(f"[Migracion] Reubicados: {migrated}")
        return migrated

    def _periodo_de_hermano(self, pdf_path: Path) -> str:
        """Periodo real desde el JSON hermano con igual stem. '' si no hay."""
        try:
            hermanos = list(pdf_path.parent.iterdir())
        except OSError:
            return ""
        for sibling in hermanos:
            if sibling.suffix.lower() != ".json":
                continue
            if self._normalizar_stem(sibling.name) != self._normalizar_stem(pdf_path.name):
                continue
            try:
                sibling_data = json.loads(sibling.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            fecha = str(self._get_identificacion(sibling_data).get("fecEmi", ""))
            if self._fecha_valida(fecha):
                return fecha[:7]
        return ""

    def backfill_db_from_jsons(self) -> int:
        """Crea filas de BD desde los JSON historicos de 02_/03_ y vincula PDFs."""
        insertados = 0
        for base in (CARPETA_PROCESADOS, CARPETA_OTROS_DTES):
            if not base.exists():
                continue
            for path in sorted(p for p in base.rglob("*.json") if p.is_file()):
                if path.name.lower().endswith("_estado.json"):
                    continue
                try:
                    try:
                        data = json.loads(path.read_text(encoding="utf-8-sig"))
                    except UnicodeDecodeError:
                        data = json.loads(path.read_text(encoding="latin-1"))
                except Exception:
                    continue
                if not self._valido(data):
                    continue
                identificacion = self._get_identificacion(data)
                codigo = self._codigo(data)
                tipo = self._tipo_final(identificacion)
                fecha = str(identificacion.get("fecEmi", ""))
                relative = path.relative_to(base)
                alias = relative.parts[0] if relative.parts else "Cliente_Desconocido"
                periodo = relative.parts[1] if len(relative.parts) > 1 else fecha[:7]
                if not db.dte_exists(codigo):
                    if db.dte_upsert(
                        alias, periodo, codigo, tipo, fecha,
                        str(identificacion.get("numeroControl", "")),
                        "", json.dumps(data),
                    ):
                        insertados += 1
                hermano = self._pdf_hermano(alias, periodo, path.name, codigo)
                if hermano:
                    db.dte_set_pdf(codigo, hermano)
        return insertados

    def _pdf_hermano(self, alias: str, periodo: str, json_name: str, codigo: str) -> str:
        """Busca el PDF del documento en 02_<alias>/<periodo>/. Retorna nombre o ''."""
        carpeta = CARPETA_PROCESADOS / alias / periodo
        if not carpeta.exists():
            return ""

        def _clave(nombre: str) -> str:
            stem = Path(nombre).stem.lower()
            stem = re.sub(r"_standard$", "", stem)
            return re.sub(r"(?:_\d+)+$", "", stem)

        clave_json = _clave(json_name)
        codigo_lower = (codigo or "").lower()
        for pdf in sorted(carpeta.glob("*.pdf")):
            if not pdf.is_file():
                continue
            if _clave(pdf.name) == clave_json:
                return pdf.name
            if codigo_lower and codigo_lower in pdf.name.lower():
                return pdf.name
        return ""

    def _get_uid_from_filename(self, filename: str) -> str:
        """Extrae el UID del nombre de archivo. Formato: ALIAS_UID_FECHA_ORIGINAL"""
        partes = filename.split('_')
        if len(partes) >= 3:
            return f"{partes[0]}_{partes[1]}" # Devuelve ALIAS_UID como agrupador seguro
        return "UNKNOWN"

    def process_downloads(self, client_filter=None, source_dir=None, destination_alias=None, should_stop=None, on_progress=None):
        """
        Flujo lineal por PDF: emparejar -> revision IA -> destino/duplicados/errores.

        - La IA revisa cada PDF. Si no devuelve datos (caso 1), el PDF original
          (+ su JSON si lo hay) va a 09_Errores.
        - Si la IA pasa (caso 2), el PDF original va a 02_Procesados (u 03_Otros
          segun tipo), la fila se guarda en BD y los JSON/markdown intermedios
          se borran: en procesados queda solo el PDF original.
        - Duplicado por codigoGeneracion (BD): a 08_Duplicados.
        - Los JSON huerfanos (sin PDF) generan fila sin PDF.
        on_progress(done, total): callback opcional de avance real.
        """
        print("[*] Iniciando procesamiento de descargas...")
        download_dir = Path(source_dir) if source_dir else CARPETA_DESCARGAS
        archivos = list(download_dir.glob("*.*"))
        if client_filter:
            client_filter = client_filter.casefold()
            archivos = [
                path for path in archivos
                if path.name.casefold().startswith(f"{client_filter}_")
            ]

        pdfs = [f for f in archivos if f.suffix.lower() == '.pdf']
        jsons = [
            f for f in archivos
            if f.suffix.lower() == '.json'
            and not f.name.lower().endswith('_estado.json')
        ]

        resultados = {"procesados_json": 0, "procesados_ocr": 0, "otros": 0, "errores": 0, "duplicados": 0}
        total_docs = len(pdfs) + len(jsons)
        done_docs = 0

        def _report_progress():
            if on_progress:
                try:
                    on_progress(done_docs, total_docs)
                except Exception:
                    pass

        def _avanzar():
            nonlocal done_docs
            done_docs += 1
            _report_progress()
            return bool(should_stop and should_stop())

        jsons_por_uid = {}
        for j in jsons:
            uid = self._get_uid_from_filename(j.name)
            jsons_por_uid.setdefault(uid, []).append(j)

        jsons_usados = set()

        for pdf in pdfs:
            # 1. Emparejar con el JSON del correo (sin generar nada en disco).
            json_path, email_data = self._emparejar_pdf(pdf, jsons_por_uid, jsons_usados)
            candidatos = [pdf]
            if json_path is not None:
                jsons_usados.add(json_path)
                if json_path.exists():
                    candidatos.append(json_path)

            # 2. Revision IA del PDF.
            ai_data = self._revisar_pdf_con_ia(pdf)

            # 3. Fuente autoritativa: JSON oficial si valido, si no la IA.
            data = email_data if self._valido(email_data) else None
            origen_ia = False
            if data is None and self._valido(ai_data):
                data = ai_data
                origen_ia = True

            if data is None:
                # CASO 1: la IA no devuelve nada -> original a errores.
                db.log_extraction(pdf.name, "ERROR", error_msg="IA sin datos (fallo, ilegible o sin clave)")
                resultados["errores"] += 1
                self._mover_a_errores(
                    candidatos,
                    self._subfolder(pdf.name, self._get_month_from_filename(pdf.name), destination_alias),
                )
                if _avanzar():
                    break
                continue

            identificacion = self._get_identificacion(data)
            tipo_dte = self._tipo_final(identificacion)
            codigo = self._codigo(data)
            fecha = str(identificacion.get("fecEmi", ""))
            alias_carpeta = self._alias_carpeta(pdf.name, destination_alias)
            subfolder = self._subfolder(pdf.name, fecha[:7], destination_alias)

            # 4. Deduplicacion por BD.
            if self._es_duplicado(data):
                self._mover_a_duplicados(candidatos, subfolder)
                db.log_extraction(pdf.name, "DUPLICATE", dte_code=tipo_dte)
                resultados["duplicados"] += 1
                if _avanzar():
                    break
                continue

            # 5. Guardar PDF original + fila en BD.
            destino = CARPETA_PROCESADOS if tipo_dte in self.target_codes else CARPETA_OTROS_DTES
            movido = self._mover_sin_sobrescribir(pdf, destino / subfolder)
            fila_ok = db.dte_upsert(
                alias_carpeta, fecha[:7], codigo, tipo_dte, fecha,
                str(identificacion.get("numeroControl", "")),
                movido.name, json.dumps(data),
            )
            if not fila_ok:
                # Choque raro de insercion: el PDF no se pierde, va a errores.
                db.log_extraction(pdf.name, "ERROR", error_msg="No se pudo guardar la fila en BD")
                resultados["errores"] += 1
                resto = [movido] + [c for c in candidatos[1:] if Path(c).exists()]
                self._mover_a_errores(resto, subfolder)
                if _avanzar():
                    break
                continue

            # 6. Borrar intermedios: en procesados queda solo el PDF original.
            for intermedio in candidatos[1:]:
                Path(intermedio).unlink(missing_ok=True)

            if tipo_dte in self.target_codes:
                db.log_extraction(pdf.name, "VALID_DTE", dte_code=tipo_dte)
                resultados["procesados_ocr" if origen_ia else "procesados_json"] += 1
            else:
                db.log_extraction(pdf.name, "OTHER_DTE", dte_code=tipo_dte)
                resultados["otros"] += 1
            if _avanzar():
                break

        # JSONs huerfanos (sin PDF): generan fila sin PDF.
        for j in [x for x in jsons if x not in jsons_usados]:
            print(f"[*] Procesando JSON huérfano: {j.name}")
            data = self._leer_json_estandarizado(j)
            if not self._valido(data):
                db.log_extraction(j.name, "ERROR", error_msg="JSON ilegible o incompleto")
                resultados["errores"] += 1
                self._mover_a_errores(
                    [j],
                    self._subfolder(j.name, self._get_month_from_filename(j.name), destination_alias),
                )
                if _avanzar():
                    break
                continue

            identificacion = self._get_identificacion(data)
            tipo_dte = self._tipo_final(identificacion)
            codigo = self._codigo(data)
            fecha = str(identificacion.get("fecEmi", ""))
            alias_carpeta = self._alias_carpeta(j.name, destination_alias)
            subfolder = self._subfolder(j.name, fecha[:7], destination_alias)

            if self._es_duplicado(data):
                self._mover_a_duplicados([j], subfolder)
                db.log_extraction(j.name, "DUPLICATE", dte_code=tipo_dte)
                resultados["duplicados"] += 1
                if _avanzar():
                    break
                continue

            if not db.dte_upsert(
                alias_carpeta, fecha[:7], codigo, tipo_dte, fecha,
                str(identificacion.get("numeroControl", "")), "", json.dumps(data),
            ):
                db.log_extraction(j.name, "ERROR", error_msg="No se pudo guardar la fila en BD")
                resultados["errores"] += 1
                self._mover_a_errores([j], subfolder)
                if _avanzar():
                    break
                continue

            j.unlink(missing_ok=True)
            if tipo_dte in self.target_codes:
                db.log_extraction(j.name, "VALID_DTE", dte_code=tipo_dte)
                resultados["procesados_json"] += 1
            else:
                db.log_extraction(j.name, "OTHER_DTE", dte_code=tipo_dte)
                resultados["otros"] += 1
            if _avanzar():
                break

        return resultados
