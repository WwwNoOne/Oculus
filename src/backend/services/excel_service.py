import json
import re
import pandas as pd
from pathlib import Path
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

    def generar_libro_compras(self, carpeta_cliente: Path, mes_anio: str, save_path: str):
        """Lee los JSONs de un mes específico y genera el libro de compras oficial con reglas estrictas."""
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
                )
                
            jsons_files = sorted(target_dir.glob("*.json"))
            if not jsons_files:
                return False, "No hay documentos JSON para generar el reporte."
                
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
                return False, "No se encontraron DTEs válidos (03, 05, 06, 14) en este periodo."
                
            # La interfaz solicita una carpeta. Crear el archivo final aqui evita
            # que pandas intente inferir el formato de una ruta sin extension.
            output_dir = Path(save_path)
            output_dir.mkdir(parents=True, exist_ok=True)
            alias = carpeta_cliente.name.strip() or "empresa"
            alias = re.sub(r'[<>:"/\\|?*]', "_", alias).strip(" .") or "empresa"
            output_file = output_dir / f"{alias}_Libro de compras_{mes_anio}.xlsx"

            df = pd.DataFrame(rows)
            df.to_excel(output_file, index=False, engine="openpyxl")
            
            return True, f"Libro de compras generado exitosamente: {output_file.name}"
            
        except Exception as e:
            return False, f"Error general: {str(e)}"
