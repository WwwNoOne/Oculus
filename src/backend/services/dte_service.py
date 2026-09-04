import os
import json
import shutil
import re
from pathlib import Path
from src.backend.utils.config import CARPETA_DESCARGAS, CARPETA_PROCESADOS, CARPETA_OTROS_DTES, CARPETA_RESPALDO_PDF
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
        """Mueve una lista de archivos a una carpeta destino, opcionalmente dentro de una subcarpeta (mes/año)"""
        target_dir = dest_folder / subfolder_name if subfolder_name else dest_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        
        for sp in source_paths:
            path = Path(sp)
            if path.exists():
                shutil.move(str(path), str(target_dir / path.name))

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
        """Reubica documentos antiguos sin reemplazar ni borrar originales validos."""
        migrated = {"json_processed": 0, "json_other": 0, "pdf_backup": 0, "ai_deleted": 0}

        # Versiones anteriores guardaban los PDF junto a los JSON procesados.
        if CARPETA_PROCESADOS.exists():
            for path in [p for p in CARPETA_PROCESADOS.rglob("*.pdf") if p.is_file()]:
                relative = path.relative_to(CARPETA_PROCESADOS)
                if len(relative.parts) >= 3:
                    self._mover_sin_sobrescribir(
                        path,
                        CARPETA_RESPALDO_PDF / relative.parts[0] / relative.parts[1],
                    )
                    migrated["pdf_backup"] += 1

        if not CARPETA_OTROS_DTES.exists():
            return migrated

        files = [p for p in CARPETA_OTROS_DTES.rglob("*") if p.is_file()]
        for path in files:
            if path.name.lower().endswith("_estado.json"):
                continue
            relative = path.relative_to(CARPETA_OTROS_DTES)
            alias = relative.parts[0] if relative.parts else "Cliente_Desconocido"
            period = relative.parts[1] if len(relative.parts) > 1 else self._get_month_from_filename(path.name)
            if period == "2000-01":
                period = self._get_month_from_filename(path.name)
            if path.suffix.lower() == ".pdf" and period in {"2000-01", "sin_fecha"}:
                for sibling in path.parent.iterdir():
                    if sibling.suffix.lower() != ".json" or self._normalizar_stem(sibling.name) != self._normalizar_stem(path.name):
                        continue
                    try:
                        sibling_data = json.loads(sibling.read_text(encoding="utf-8-sig"))
                        sibling_identification = self._get_identificacion(sibling_data)
                        sibling_date = str(sibling_identification.get("fecEmi", ""))
                        if re.match(r"^\d{4}-\d{2}", sibling_date):
                            period = sibling_date[:7]
                    except (OSError, ValueError, UnicodeDecodeError):
                        pass
            subfolder = f"{alias}/{period}"

            if path.suffix.lower() == ".pdf":
                self._mover_sin_sobrescribir(path, CARPETA_RESPALDO_PDF / subfolder)
                migrated["pdf_backup"] += 1
                continue
            if path.suffix.lower() != ".json":
                continue

            try:
                try:
                    data = json.loads(path.read_text(encoding="utf-8-sig"))
                except UnicodeDecodeError:
                    data = json.loads(path.read_text(encoding="latin-1"))
            except Exception:
                continue

            identification = self._get_identificacion(data)
            tipo = str(identification.get("tipoDte", "")).zfill(2)
            if tipo == "00":
                control = str(identification.get("numeroControl", "")).upper()
                for code in self.target_codes:
                    if f"DTE-{code}" in control:
                        tipo = code
                        break

            if self._is_ai_garbage(data, identification, tipo):
                path.unlink(missing_ok=True)
                migrated["ai_deleted"] += 1
                continue

            fecha = str(identification.get("fecEmi", ""))
            if re.match(r"^\d{4}-\d{2}", fecha):
                subfolder = f"{alias}/{fecha[:7]}"
            destination_root = CARPETA_PROCESADOS if tipo in self.target_codes else CARPETA_OTROS_DTES
            self._mover_sin_sobrescribir(path, destination_root / subfolder)
            migrated["json_processed" if tipo in self.target_codes else "json_other"] += 1

        if any(migrated.values()):
            print(f"[Migracion] Documentos reubicados: {migrated}")
        return migrated

    def _get_uid_from_filename(self, filename: str) -> str:
        """Extrae el UID del nombre de archivo. Formato: ALIAS_UID_FECHA_ORIGINAL"""
        partes = filename.split('_')
        if len(partes) >= 3:
            return f"{partes[0]}_{partes[1]}" # Devuelve ALIAS_UID como agrupador seguro
        return "UNKNOWN"

    def process_downloads(self, client_filter=None, source_dir=None, destination_alias=None, should_stop=None):
        """
        Escanea la carpeta de descargas, empareja PDFs con JSONs usando el UID del correo 
        o procesa PDFs huérfanos mediante OCR/IA.
        """
        print("[*] Iniciando procesamiento matemático de descargas...")
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
        
        resultados = {"procesados_json": 0, "procesados_ocr": 0, "otros": 0, "errores": 0}
        
        # Agrupar JSONs por ALIAS_UID
        jsons_por_uid = {}
        for j in jsons:
            uid = self._get_uid_from_filename(j.name)
            if uid not in jsons_por_uid:
                jsons_por_uid[uid] = []
            jsons_por_uid[uid].append(j)
            
        jsons_usados = set()

        for pdf in pdfs:
            pdf_emparejado = False
            json_asociado_data = None
            json_asociado_path = None
            
            uid = self._get_uid_from_filename(pdf.name)
            posibles_jsons = jsons_por_uid.get(uid, [])
            posibles_jsons = [j for j in posibles_jsons if j not in jsons_usados]
            
            # ESTRATEGIA 1 y 2: nombre, UUID o numero de control compartido.
            puntuados = sorted(
                ((self._pair_score(pdf.name, j.name), j) for j in posibles_jsons),
                key=lambda item: item[0],
                reverse=True,
            )
            if puntuados and puntuados[0][0] > 0 and (
                len(puntuados) == 1 or puntuados[0][0] > puntuados[1][0]
            ):
                j = puntuados[0][1]
                json_asociado_path = j
                json_asociado_data = self._leer_json_estandarizado(j)
                if json_asociado_data:
                    with open(j, 'w', encoding='utf-8') as f:
                        json.dump(json_asociado_data, f, indent=4)
                jsons_usados.add(j)
                pdf_emparejado = True
                    
            # ESTRATEGIA 2: Emparejamiento por UID (Si los llamaron distinto, pero solo hay 1 par en el correo)
            if not pdf_emparejado and len(posibles_jsons) == 1:
                # Ojo: Solo lo hacemos si es seguro (1 a 1). Si hay 2 PDFs y 2 JSONs revueltos, cae a OCR
                j = posibles_jsons[0]
                json_asociado_path = j
                json_asociado_data = self._leer_json_estandarizado(j)
                
                if json_asociado_data:
                    with open(j, 'w', encoding='utf-8') as f:
                        json.dump(json_asociado_data, f, indent=4)
                        
                jsons_usados.add(j)
                pdf_emparejado = True
                print(f"[*] Emparejamiento heurístico: {pdf.name} <-> {j.name}")
                
            # ESTRATEGIA 3: Fallback a Inteligencia Artificial (Huérfano o Corrupto)
            if not pdf_emparejado:
                print(f"[*] Fallback a OCR para PDF huérfano: {pdf.name}")
                try:
                    raw_json = self.ocr.process_pdf_to_raw_json(str(pdf))
                    json_asociado_data = self.ocr.parse_raw_to_standard(raw_json)
                    
                    json_asociado_path = download_dir / f"{pdf.stem}_standard.json"
                    with open(json_asociado_path, 'w', encoding='utf-8') as f:
                        json.dump(json_asociado_data, f, indent=4)
                        
                    resultados["procesados_ocr"] += 1
                except Exception as e:
                    db.log_extraction(pdf.name, "ERROR", error_msg=str(e))
                    resultados["errores"] += 1
                    continue
            # Filtrado por tipoDte (03, 05, 06, 14)
            if json_asociado_data:
                identificacion = self._get_identificacion(json_asociado_data)
                tipo_dte = str(identificacion.get("tipoDte", "")).zfill(2)
                
                # Rescate por si viene en el número de control (Fallback de seguridad)
                if not tipo_dte or tipo_dte == "00":
                    control = str(identificacion.get("numeroControl", "")).upper()
                    for t in self.target_codes:
                        if f"DTE-{t}" in control:
                            tipo_dte = t
                            break

                fecha = str(identificacion.get("fecEmi", ""))
                mes_anio = fecha[:7] if re.match(r"^\d{4}-\d{2}", fecha) else self._get_month_from_filename(pdf.name)
                
                # Extraer cliente del nombre del archivo (el ALIAS es la primera parte antes del _)
                # Para evitar duplicados en mayúsculas/minúsculas u OCR impreciso
                partes_nombre = pdf.name.split('_')
                if destination_alias:
                    cliente = destination_alias
                elif len(partes_nombre) > 1:
                    cliente = partes_nombre[0]
                else:
                    cliente = "Cliente_Desconocido"
                
                cliente_folder = "".join(x for x in cliente if x.isalnum() or x in " -_").strip()
                subfolder = f"{cliente_folder}/{mes_anio}"

                json_para_mover = [json_asociado_path] if json_asociado_path and json_asociado_path.exists() else []

                if tipo_dte in self.target_codes:
                    self._mover_archivos([pdf], CARPETA_RESPALDO_PDF, subfolder)
                    self._mover_archivos(json_para_mover, CARPETA_PROCESADOS, subfolder)
                    db.log_extraction(pdf.name, "VALID_DTE", dte_code=tipo_dte)
                    resultados["procesados_json"] += 1 if json_asociado_path else 0
                else:
                    if json_asociado_path and self._is_ai_garbage(json_asociado_data, identificacion, tipo_dte):
                        # El PDF queda como respaldo; se elimina solo el JSON IA inutil.
                        json_asociado_path.unlink(missing_ok=True)
                        json_para_mover = []
                    self._mover_archivos([pdf], CARPETA_RESPALDO_PDF, subfolder)
                    self._mover_archivos(json_para_mover, CARPETA_OTROS_DTES, subfolder)
                    db.log_extraction(pdf.name, "OTHER_DTE", dte_code=tipo_dte)
                    resultados["otros"] += 1
                if should_stop and should_stop():
                    break

        # Procesar JSONs huérfanos (que no vinieron con PDF)
        jsons_huerfanos = [j for j in jsons if j not in jsons_usados]
        for j in jsons_huerfanos:
            print(f"[*] Estandarizando JSON huérfano: {j.name}")
            json_asociado_data = self._leer_json_estandarizado(j)
            
            if json_asociado_data:
                with open(j, 'w', encoding='utf-8') as f:
                    json.dump(json_asociado_data, f, indent=4)
                    
                identificacion = self._get_identificacion(json_asociado_data)
                tipo_dte = str(identificacion.get("tipoDte", "")).zfill(2)
                if not tipo_dte or tipo_dte == "00":
                    control = str(identificacion.get("numeroControl", "")).upper()
                    for t in self.target_codes:
                        if f"DTE-{t}" in control:
                            tipo_dte = t
                            break

                fecha = str(identificacion.get("fecEmi", ""))
                mes_anio = fecha[:7] if re.match(r"^\d{4}-\d{2}", fecha) else self._get_month_from_filename(j.name)
                
                partes_nombre = j.name.split('_')
                if destination_alias:
                    cliente = destination_alias
                elif len(partes_nombre) > 1:
                    cliente = partes_nombre[0]
                else:
                    cliente = "Cliente_Desconocido"
                    
                cliente_folder = "".join(x for x in cliente if x.isalnum() or x in " -_").strip()
                subfolder = f"{cliente_folder}/{mes_anio}"

                if tipo_dte in self.target_codes:
                    self._mover_archivos([j], CARPETA_PROCESADOS, subfolder)
                    db.log_extraction(j.name, "VALID_DTE", dte_code=tipo_dte)
                    resultados["procesados_json"] += 1
                else:
                    if self._is_ai_garbage(json_asociado_data, identificacion, tipo_dte):
                        j.unlink(missing_ok=True)
                        db.log_extraction(j.name, "DISCARDED_AI_JSON", dte_code=tipo_dte)
                        continue
                    self._mover_archivos([j], CARPETA_OTROS_DTES, subfolder)
                    db.log_extraction(j.name, "OTHER_DTE", dte_code=tipo_dte)
                    resultados["otros"] += 1
                if should_stop and should_stop():
                    break

        return resultados
