import json
import re
import shutil
import pandas as pd
from pathlib import Path
from src.backend.utils.config import CARPETA_PROCESADOS, CARPETA_ERRORES
from src.backend.database.db_manager import db
from src.backend.utils.json_utils import extract_identificacion, get_document_sections, extract_sello, get_sello_from_mh_response, fecha_emision_valida

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

    def _fila_desde_data(self, data, correlativo):
        """Construye la fila del libro desde el JSON estandarizado.

        Retorna (row, codigo) o (None, codigo) si el tipo no es de compras.
        """
        documento = self._get_document(data)
        identificacion = extract_identificacion(data)

        # Fecha real obligatoria tambien en la entrega (mata 2000/00/00).
        if not fecha_emision_valida(identificacion.get("fecEmi", "")):
            return None, ""

        # 1. Filtro estricto por Tipo DTE
        tipo_dte = self._extract_tipo_dte(identificacion)
        if tipo_dte not in ["03", "05", "06", "14"]:
            return None, ""

        codigo = str(identificacion.get("codigoGeneracion", "") or "").strip().upper()

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

        return row, codigo

    def generar_libro_compras(self, carpeta_cliente: Path, mes_anio: str, save_path: str):
        """Genera el libro de compras desde las filas guardadas en BD al procesar.

        Crea una carpeta de entrega `<save_path>/<alias>_<mes>/` con el .xlsx,
        `JSON/` (regenerados desde la BD), `PDF/` (originales de 02_Procesados)
        y `Errores/` (fallidos de 09_Errores). Solo copia, nunca mueve.

        Retorna (success, mensaje, ruta_carpeta_entrega | None).
        """
        try:
            alias = (carpeta_cliente.name or "").strip() or "empresa"
            alias = re.sub(r'[<>:"/\\|?*]', "_", alias).strip(" .") or "empresa"

            filas = db.get_dte_rows(alias, mes_anio)
            if not filas:
                periodos = sorted(
                    folder.name for folder in carpeta_cliente.iterdir()
                    if folder.is_dir()
                ) if carpeta_cliente.exists() else []
                detalle = ", ".join(periodos) or "ninguno"
                return False, (
                    f"No hay documentos procesados para {alias} en {mes_anio}. "
                    f"Períodos disponibles: {detalle}."
                ), None

            rows = []
            usados = []  # (pdf_name, data, codigo)
            correlativo = 1
            # Barrera anti-duplicados (la BD ya garantiza codigo unico).
            vistos = set()

            for rec in filas:
                try:
                    data = rec.get("data") or {}
                    if not isinstance(data, dict):
                        continue
                    row, codigo = self._fila_desde_data(data, correlativo)
                    if row is None:
                        continue
                    if codigo:
                        if codigo in vistos:
                            print(f"[{codigo}] Omitido por duplicado en entrega")
                            continue
                        vistos.add(codigo)
                    rows.append(row)
                    usados.append((rec.get("pdf_name") or "", data, codigo or f"doc_{correlativo}"))
                    correlativo += 1
                except Exception as e:
                    print(f"Error armando fila {rec.get('codigo_generacion')}: {e}")

            if not rows:
                return False, "No se encontraron DTEs válidos (03, 05, 06, 14) en este periodo.", None

            # Carpeta de entrega: <destino>/<alias>_<mes>/ (sufijo automatico si existe).
            output_base = Path(save_path)
            output_base.mkdir(parents=True, exist_ok=True)
            delivery_dir = output_base / f"{alias}_{mes_anio}"
            sufijo = 2
            while delivery_dir.exists():
                delivery_dir = output_base / f"{alias}_{mes_anio}_{sufijo}"
                sufijo += 1
            json_dir = delivery_dir / "JSON"
            pdf_dir = delivery_dir / "PDF"
            errores_dir = delivery_dir / "Errores"
            json_dir.mkdir(parents=True, exist_ok=True)
            pdf_dir.mkdir(parents=True, exist_ok=True)
            output_file = delivery_dir / f"{alias}_Libro de compras_{mes_anio}.xlsx"

            df = pd.DataFrame(rows)
            df.to_excel(output_file, index=False, engine="openpyxl")

            # JSON regenerados desde la BD (la entrega mantiene el formato anterior).
            for _pdf_name, data, codigo in usados:
                nombre = re.sub(r'[<>:"/\\|?*]', "_", codigo).strip(" .") or "documento"
                try:
                    with open(json_dir / f"{nombre}.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=4, ensure_ascii=False)
                except Exception as e:
                    print(f"No se pudo exportar JSON {nombre}: {e}")

            # PDF originales desde 02_Procesados/<alias>/<mes>/.
            pdf_origen = CARPETA_PROCESADOS / alias / mes_anio
            sin_pdf = 0
            for pdf_name, _data, _codigo in usados:
                origen = pdf_origen / pdf_name if pdf_name else None
                if origen is not None and origen.is_file():
                    try:
                        shutil.copy2(str(origen), str(pdf_dir / origen.name))
                    except Exception as e:
                        print(f"No se pudo copiar {origen.name} a la entrega: {e}")
                        sin_pdf += 1
                else:
                    sin_pdf += 1

            # Errores del periodo incluidos en la entrega.
            n_errores = 0
            error_origen = CARPETA_ERRORES / alias / mes_anio
            if error_origen.exists():
                errores_dir.mkdir(parents=True, exist_ok=True)
                for err in sorted(p for p in error_origen.iterdir() if p.is_file()):
                    try:
                        shutil.copy2(str(err), str(errores_dir / err.name))
                        n_errores += 1
                    except Exception as e:
                        print(f"No se pudo copiar error {err.name}: {e}")

            con_pdf = len(usados) - sin_pdf
            mensaje = (
                f"Libro de compras generado: {output_file.name}. "
                f"Documentos exportados: {len(usados)} "
                f"({con_pdf} con PDF, {sin_pdf} sin PDF, {n_errores} con errores). "
                f"Carpeta de entrega: {delivery_dir}"
            )
            return True, mensaje, str(delivery_dir)

        except Exception as e:
            return False, f"Error general: {str(e)}", None
