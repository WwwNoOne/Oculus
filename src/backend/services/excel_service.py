import json
import re
import shutil
import pandas as pd
from pathlib import Path
from src.backend.utils.config import CARPETA_RESPALDO_PDF
from src.backend.utils.json_utils import extract_identificacion, get_document_sections, extract_sello, get_sello_from_mh_response

class ExcelService:
    def __init__(self):
        self.columns = [
            'No. Correlativo', 'Fecha de Emision', 'CODIGO DE GENERACION', 'N.R.C.', 
            'NIT,CIP,DUI del Sujeto Excluido', 'Nombre del Proveedor', 'Compras a Sujetos Excluidos', 
            'FOVIAL/ COTRANS/ CESC', 'COMPRAS EXENTAS - Internas', 'COMPRAS EXENTAS - Importaciones', 
            'COMPRAS GRAVADAS - Internas', 'COMPRAS GRAVADAS - Importaciones', 'Credito Fiscal', 
            'IVA Percibido', 'TOTAL Compras', 'Impuesto 0.02', 'Impuesto Retenido a Terceros', 
            'COMPRAS NO SUJETAS', 'SERIE / SELLO DE RECEPCION', 'No DE CONTROL /RESOLUCION', 
            'TIPO DE OPERACION', 'CLASIFICACION', 'TIPO DE COSTO /GASTO', 'CONCEPTO IVA'
        ]

    def _extract_tipo_dte(self, identificacion):
        tipo = str(identificacion.get("tipoDte", "")).zfill(2)
        if tipo in ["03", "05", "06", "14"]:
            return tipo
            
        control = str(identificacion.get("numeroControl", "")).upper()
        if "DTE-03" in control: return "03"
        if "DTE-05" in control: return "05"
        if "DTE-06" in control: return "06"
        if "DTE-14" in control: return "14"
        
        return "UNKNOWN"

    def _get_document(self, data):
        detalle = data.get("detalleDTE")
        if isinstance(detalle, dict) and not data.get("identificacion"):
            return detalle
        return data

    def _extract_tributos_especiales(self, tributos):
        percibido = 0.0
        retenido = 0.0
        if isinstance(tributos, str):
            try:
                tributos = json.loads(tributos)
            except (TypeError, ValueError):
                return percibido, retenido
        if isinstance(tributos, dict):
            tributos = [tributos]
        if not isinstance(tributos, list):
            return percibido, retenido
        
        for t in tributos:
            if not isinstance(t, dict):
                continue
            desc = str(t.get("descripcion", "")).lower()
            val = float(t.get("valor", 0.0))
            if "percibido" in desc or str(t.get("codigo", "")) in ["21", "C21"]:
                percibido += val
            elif "retenido" in desc or "retencion" in desc or str(t.get("codigo", "")) in ["22", "C22", "11"]:
                retenido += val
        return percibido, retenido

    @staticmethod
    def _stem_key(filename: str) -> str:
        """Clave de emparejamiento JSON<->PDF: minusculas, sin _standard ni sufijos _N."""
        stem = Path(filename).stem.lower()
        stem = re.sub(r"(?:_\d+)+$", "", stem)
        stem = re.sub(r"_standard$", "", stem)
        stem = re.sub(r"(?:_\d+)+$", "", stem)
        return stem

    def _codigo_de_archivo(self, json_path: Path) -> str:
        """Lee el codigoGeneracion de un JSON ya guardado. Retorna "" si no se puede leer."""
        try:
            try:
                data = json.loads(json_path.read_text(encoding="utf-8-sig"))
            except UnicodeDecodeError:
                data = json.loads(json_path.read_text(encoding="latin-1"))
            return str(extract_identificacion(data).get("codigoGeneracion", "") or "").strip()
        except Exception:
            return ""

    def generar_libro_compras(self, carpeta_cliente: Path, mes_anio: str, save_path: str):
        """Lee los JSONs de un mes específico y genera el libro de compras oficial con reglas estrictas.

        Crea una carpeta de entrega `<save_path>/<alias>_<mes>/` con el .xlsx en la raiz
        y subcarpetas `JSON/` (copias de los JSON incluidos) y `PDF/` (copias de sus PDF
        de respaldo). Nunca mueve originales: solo copia.

        Retorna (success, mensaje, ruta_carpeta_entrega | None).
        """
        try:
            target_dir = carpeta_cliente / mes_anio
            if not target_dir.exists():
                disponibles = sorted(
                    folder.name for folder in carpeta_cliente.iterdir()
                    if folder.is_dir()
                ) if carpeta_cliente.exists() else []
                detalle = ", ".join(disponibles) or "ninguno"
                return False, (
                    f"La carpeta de datos no existe: {target_dir}. "
                    f"Períodos disponibles para este cliente: {detalle}."
                ), None
                
            jsons_files = sorted(target_dir.glob("*.json"))
            if not jsons_files:
                return False, "No hay documentos JSON para generar el reporte.", None
                
            rows = []
            correlativo = 1
            # Segunda barrera anti-duplicados: un mismo codigoGeneracion solo entra una vez.
            vistos = set()
            # JSON realmente incluidos en el libro (para la carpeta de entrega).
            usados = []

            for jf in jsons_files:
                try:
                    try:
                        data = json.loads(jf.read_text(encoding='utf-8-sig'))
                    except UnicodeDecodeError:
                        data = json.loads(jf.read_text(encoding='latin-1'))

                    documento = self._get_document(data)
                    identificacion = extract_identificacion(data)

                    codigo = str(identificacion.get("codigoGeneracion", "") or "").strip().upper()
                    if codigo:
                        if codigo in vistos:
                            print(f"[{jf.name}] Omitido por duplicado (codigoGeneracion {codigo})")
                            continue
                        vistos.add(codigo)

                    # 1. Filtro estricto por Tipo DTE
                    tipo_dte = self._extract_tipo_dte(identificacion)
                    if tipo_dte not in ["03", "05", "06", "14"]:
                        print(f"[{jf.name}] Saltando documento no admitido para compras (Tipo {tipo_dte})")
                        continue
                        
                    emisor = get_document_sections(data, "emisor")
                    resumen = get_document_sections(data, "resumen")
                    sello_dict = get_document_sections(data, "selloRecepcion")
                    sello_variante = extract_sello(data)
                    sello_mh = get_sello_from_mh_response(data)
                    
                    row = {col: "" for col in self.columns}
                    row['No. Correlativo'] = correlativo
                    row['Fecha de Emision'] = identificacion.get("fecEmi", "")
                    row['CODIGO DE GENERACION'] = identificacion.get("codigoGeneracion", "")
                    row['N.R.C.'] = emisor.get("nrc", "")
                    row['NIT,CIP,DUI del Sujeto Excluido'] = emisor.get("nit", "")
                    row['Nombre del Proveedor'] = emisor.get("nombre", "Desconocido")
                    row['SERIE / SELLO DE RECEPCION'] = (sello_dict.get("selloRecepcion") or sello_variante or sello_mh or "")
                    row['No DE CONTROL /RESOLUCION'] = identificacion.get("numeroControl", "")
                    
                    # Extracción base (Asumiendo que ya tiene descuentos restados por diseño de Hacienda)
                    subtotal_base = float(resumen.get("totalGravada", 0.0) or resumen.get("subTotal", 0.0))
                    otros_impuestos = float(data.get("otros_impuestos_manuales", 0.0))
                    
                    # Tributos Especiales
                    percibido, retenido = self._extract_tributos_especiales(resumen.get("tributos", []))
                    
                    # Aplicar Lógica de Negocio
                    if tipo_dte == "14":
                        # DTE 14: Sujeto Excluido
                        row['Compras a Sujetos Excluidos'] = subtotal_base
                        row['COMPRAS GRAVADAS - Internas'] = 0.0
                        row['Credito Fiscal'] = 0.0
                        row['Impuesto Retenido a Terceros'] = retenido
                        row['TOTAL Compras'] = subtotal_base - retenido # El total suele ser subtotal menos retencion
                        if otros_impuestos > 0: row['FOVIAL/ COTRANS/ CESC'] = otros_impuestos
                        
                    else:
                        # DTE 03, 05, 06
                        iva_matematico = subtotal_base * 0.13
                        row['COMPRAS GRAVADAS - Internas'] = subtotal_base
                        row['Credito Fiscal'] = iva_matematico
                        row['IVA Percibido'] = percibido
                        row['Impuesto Retenido a Terceros'] = retenido
                        if otros_impuestos > 0: row['FOVIAL/ COTRANS/ CESC'] = otros_impuestos
                        
                        # Total (sumando todo matemáticamente para máxima precisión)
                        total = subtotal_base + iva_matematico + percibido - retenido + otros_impuestos
                        row['TOTAL Compras'] = total
                        
                        # DTE 05: Nota de Crédito (Invertir signos)
                        if tipo_dte == "05":
                            for col in ['COMPRAS GRAVADAS - Internas', 'Credito Fiscal', 'IVA Percibido', 'Impuesto Retenido a Terceros', 'FOVIAL/ COTRANS/ CESC', 'TOTAL Compras']:
                                if isinstance(row[col], (int, float)) and row[col] > 0:
                                    row[col] *= -1

                    rows.append(row)
                    usados.append(jf)
                    correlativo += 1
                    
                except Exception as e:
                    print(f"Error parseando {jf.name}: {e}")
                    
            if not rows:
                return False, "No se encontraron DTEs válidos (03, 05, 06, 14) en este periodo.", None

            # Carpeta de entrega: <destino>/<alias>_<mes>/ con el .xlsx, JSON/ y PDF/.
            # Si ya existe, se crea un sufijo automatico (_2, _3...) en vez de sobrescribir.
            output_base = Path(save_path)
            output_base.mkdir(parents=True, exist_ok=True)
            alias = carpeta_cliente.name.strip() or "empresa"
            alias = re.sub(r'[<>:"/\\|?*]', "_", alias).strip(" .") or "empresa"
            delivery_dir = output_base / f"{alias}_{mes_anio}"
            sufijo = 2
            while delivery_dir.exists():
                delivery_dir = output_base / f"{alias}_{mes_anio}_{sufijo}"
                sufijo += 1
            json_dir = delivery_dir / "JSON"
            pdf_dir = delivery_dir / "PDF"
            json_dir.mkdir(parents=True, exist_ok=True)
            pdf_dir.mkdir(parents=True, exist_ok=True)
            output_file = delivery_dir / f"{alias}_Libro de compras_{mes_anio}.xlsx"

            df = pd.DataFrame(rows)
            df.to_excel(output_file, index=False, engine="openpyxl")

            # Copiar (nunca mover) solo los JSON realmente incluidos en el libro.
            for jf in usados:
                try:
                    shutil.copy2(str(jf), str(json_dir / jf.name))
                except Exception as e:
                    print(f"No se pudo copiar {jf.name} a la entrega: {e}")

            # Emparejar cada JSON con su PDF de respaldo (05_Respaldo_PDF/<cliente>/<mes>/).
            pdf_origen = CARPETA_RESPALDO_PDF / carpeta_cliente.name / mes_anio
            pdfs_respaldo = list(pdf_origen.glob("*.pdf")) if pdf_origen.exists() else []
            pdf_por_stem = {}
            for pdf in pdfs_respaldo:
                pdf_por_stem.setdefault(self._stem_key(pdf.name), pdf)
            sin_pdf = 0
            for jf in usados:
                match = pdf_por_stem.get(self._stem_key(jf.name))
                if match is None:
                    codigo = self._codigo_de_archivo(jf)
                    if codigo:
                        codigo_lower = codigo.lower()
                        match = next(
                            (pdf for pdf in pdfs_respaldo if codigo_lower in pdf.name.lower()),
                            None,
                        )
                if match is not None:
                    try:
                        shutil.copy2(str(match), str(pdf_dir / match.name))
                    except Exception as e:
                        print(f"No se pudo copiar {match.name} a la entrega: {e}")
                        sin_pdf += 1
                else:
                    sin_pdf += 1

            con_pdf = len(usados) - sin_pdf
            mensaje = (
                f"Libro de compras generado: {output_file.name}. "
                f"Documentos exportados: {len(usados)} "
                f"({con_pdf} con PDF, {sin_pdf} sin PDF). "
                f"Carpeta de entrega: {delivery_dir}"
            )
            return True, mensaje, str(delivery_dir)

        except Exception as e:
            return False, f"Error general: {str(e)}", None
