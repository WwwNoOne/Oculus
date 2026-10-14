import os
import json
import fitz  # PyMuPDF
import requests
from pathlib import Path
from src.backend.utils.config import DATA_DIR
from src.backend.utils.json_utils import extract_identificacion, find_section

try:
    from google import genai
except ImportError:
    genai = None

try:
    import warnings as _warnings

    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore", DeprecationWarning)
        from llama_parse import LlamaParse
except ImportError:
    LlamaParse = None

class OCRService:
    DEEPSEEK_MODEL = "deepseek-v4-flash"
    GEMINI_MODEL = "gemini-3.6-flash"
    AI_TIMEOUT_SECONDS = 180

    def __init__(self):
        # 1. Intentar cargar desde el settings.json local
        self.deepseek_api_key = self._load_api_key("deepseek") or os.getenv("DEEPSEEK_API_KEY", "")
        self.gemini_api_key = self._load_api_key("gemini") or os.getenv("GEMINI_API_KEY", "")
        # LlamaParse (vision para PDFs escaneados; plan gratuito generoso).
        self.llamaparse_api_key = self._load_api_key("llamaparse") or os.getenv("LLAMA_CLOUD_API_KEY", "")

    def _load_api_key(self, key_name: str) -> str:
        try:
            settings_path = DATA_DIR / "settings.json"
            if settings_path.exists():
                with open(settings_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    val = settings.get(key_name, "")
                    if val:
                        from src.backend.utils.crypto import decrypt_data
                        val = decrypt_data(val)
                    return val
        except Exception as e:
            print(f"Error cargando settings: {e}")
        return ""

    def _extract_local_text(self, pdf_path: str) -> str:
        """Extrae el texto del PDF localmente usando PyMuPDF (Costo $0)"""
        try:
            doc = fitz.open(pdf_path)
            texto = ""
            for page in doc:
                texto += page.get_text() + "\n"
            return texto.strip()
        except Exception as e:
            print(f"Error extrayendo texto de {pdf_path}: {e}")
            return ""

    def _generate_json(self, prompt: str) -> dict:
        """Usa DeepSeek y deja Gemini como respaldo opcional."""
        errors = []
        if self.deepseek_api_key:
            try:
                response = requests.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {self.deepseek_api_key}"},
                    json={"model": self.DEEPSEEK_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 1024, "response_format": {"type": "json_object"}},
                    timeout=self.AI_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                return self._parse_json_response(response.json()["choices"][0]["message"]["content"])
            except Exception as exc:
                errors.append(f"DeepSeek: {exc}")

        if self.gemini_api_key:
            try:
                if genai:
                    client = genai.Client(api_key=self.gemini_api_key)
                    response = client.models.generate_content(
                        model=self.GEMINI_MODEL,
                        contents=prompt,
                        config={"response_mime_type": "application/json", "max_output_tokens": 1024},
                    )
                    text = response.text
                else:
                    response = requests.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{self.GEMINI_MODEL}:generateContent",
                        params={"key": self.gemini_api_key},
                        json={"contents": [{"parts": [{"text": prompt}]}]},
                        timeout=self.AI_TIMEOUT_SECONDS,
                    )
                    response.raise_for_status()
                    body = response.json()
                    text = body["candidates"][0]["content"]["parts"][0]["text"]
                return self._parse_json_response(text)
            except Exception as exc:
                errors.append(f"Gemini: {exc}")

        raise RuntimeError("; ".join(errors) or "No hay un proveedor de IA configurado")

    def _parse_json_response(self, content: str) -> dict:
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:-3]
        elif content.startswith("```"):
            content = content[3:-3]
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            start = min((i for i in (content.find("{"), content.find("[")) if i >= 0), default=-1)
            end = max(content.rfind("}"), content.rfind("]"))
            if start < 0 or end < start:
                raise
            return json.loads(content[start:end + 1])

    def _extract_with_llamaparse(self, pdf_path: str) -> str:
        """Extrae texto de PDFs escaneados con LlamaParse (vision).

        Solo se llama cuando hay clave configurada y el PDF no tiene texto
        extraible, asi no se consume credito en documentos normales.
        """
        if not self.llamaparse_api_key or LlamaParse is None:
            return ""
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                parser = LlamaParse(api_key=self.llamaparse_api_key, result_type="markdown")
                documents = parser.load_data(pdf_path)
            textos = [getattr(doc, "text", "") or "" for doc in (documents or [])]
            return "\n".join(textos).strip()
        except Exception as e:
            print(f"[!] LlamaParse fallo para {pdf_path}: {e}")
            return ""

    def process_pdf_to_raw_json(self, pdf_path: str) -> dict:
        """
        Tubería principal: PyMuPDF -> DeepSeek -> JSON Crudo
        """
        print(f"[*] Iniciando Extracción Híbrida (PyMuPDF + DeepSeek) para: {pdf_path}")
        
        # 1. Extracción gratuita
        texto_crudo = self._extract_local_text(pdf_path)

        # 1b. PDF escaneado (sin texto): vision con LlamaParse antes de rendirse.
        if (not texto_crudo or len(texto_crudo) < 50) and self.llamaparse_api_key:
            print("[*] PDF escaneado detectado. Extrayendo con LlamaParse...")
            texto_crudo = self._extract_with_llamaparse(pdf_path)

        if not texto_crudo or len(texto_crudo) < 50:
            print("[!] PDF escaneado sin texto util. Configure LlamaParse para vision.")
            return {"error": "documento_escaneado", "requires_vision": True}
        
        # 2. Estructuración con DeepSeek (Gemini queda como respaldo)
        if not self.deepseek_api_key and not self.gemini_api_key:
            print("[!] No hay API Key de DeepSeek ni Gemini. Simulando respuesta.")
            return self._mock_response(pdf_path)
            
        prompt = f"""
        Eres un asistente experto en contabilidad. Extrae la siguiente información del texto de este Documento Tributario Electrónico (DTE).
        Debes responder ÚNICAMENTE con un JSON válido. No incluyas explicaciones, ni bloques markdown como ```json.
        
        REGLAS DE EXTRACCIÓN:
        1. La fecha de emisión es identificacion.fecEmi. NO uses otra fecha del documento como vencimiento, finalización, presentación, generación o transacción.
        2. El sello oficial puede aparecer como selloRecibido, selloRecepcion o dentro de una sección respuestaMH/selloRecibido. Solo usa el sello real, no un número de resolución.
        3. Si el sello no existe, devuelve selloRecepcion con cadena vacía y NO lo inventes.
        4. tipoDte es el código que está en la identificación del DTE. Si el documento no es un DTE, devuelve tipoDte UNKNOWN.
        5. Los valores numéricos deben copiarse como están, sin redondear.
        
        Estructura requerida:
        {{
            "identificacion": {{
                "codigoGeneracion": "UUID de 36 caracteres",
                 "tipoDte": "tipo DTE real, por ejemplo 01, 03, 05, 06, 07 o 14",
                "numeroControl": "DTE-...",
                "fecEmi": "YYYY-MM-DD"
            }},
            "emisor": {{
                "nombre": "Nombre de la empresa",
                "nit": "NIT de la empresa",
                "nrc": "NRC"
            }},
            "resumen": {{
                "totalPagar": 0.00,
                "totalCompra": 0.00,
                "iva": 0.00,
                "ivaPerci1": 0.00,
                "ivaRete1": 0.00
            }},
            "selloRecepcion": {{
                "selloRecepcion": "Cadena real del sello o cadena vacía"
            }}
        }}
        
        Texto DTE:
        {texto_crudo}
        """
        
        try:
            return self._generate_json(prompt)
            
        except Exception as e:
            print(f"[!] Error procesando con DeepSeek/Gemini: {e}")
            return {"error": "fallo_ia", "mensaje": str(e)}

    def parse_raw_to_standard(self, raw_json: dict) -> dict:
        """Transforma el JSON crudo en el formato estándar del sistema"""
        estandar_json = raw_json.copy()
        estandar_json["_metadata"] = {
            "fuente": "IA",
            "estado": "Procesado con IA",
            "estandarizado": True,
        }
        return estandar_json

    def process_raw_json_text(self, json_text: str) -> dict:
        """
        Toma el texto de un JSON que puede venir deforme o con otros nombres de variables,
        y lo pasa por DeepSeek para que nos devuelva la estructura inmaculada y oficial.
        """
        print("[*] Estandarizando JSON crudo a través de DeepSeek...")

        # Los DTE oficiales ya estructurados no necesitan consumir IA.
        try:
            local_data = json.loads(json_text)
            local_identification = extract_identificacion(local_data)
            local_document = local_data
            if not local_identification.get("tipoDte"):
                local_document = find_section(local_data, "detalleDTE")
                local_identification = extract_identificacion(local_document) if isinstance(local_document, dict) else {}
            if (isinstance(local_identification, dict)
                    and local_identification.get("tipoDte")
                    and find_section(local_document, "emisor")
                    and find_section(local_document, "resumen")):
                return local_data
        except (TypeError, ValueError):
            pass
        
        if not self.deepseek_api_key and not self.gemini_api_key:
            print("[!] No hay API Key de DeepSeek ni Gemini. Devolviendo JSON original como fallback.")
            try:
                return json.loads(json_text)
            except:
                return self._mock_response("json_fallback")
                
        prompt = f"""
        Eres un purificador de datos. El siguiente texto es un JSON (posiblemente con claves mal nombradas, anidadas o extrañas) que representa un Documento Tributario Electrónico (DTE) de El Salvador.
        Extrae la información vital y mapeala EXACTAMENTE a la siguiente estructura JSON. 
        Si un valor es numérico, ponlo como número.
        No incluyas explicaciones, ni bloques markdown como ```json. Solo responde con el JSON.
        
        REGLAS OBLIGATORIAS:
        1. Identificacion.fecEmi es la fecha de emisión. NO sustituyas por la fecha de cierre, facturación, recepción, vencimiento o generación.
        2. El sello puede venir como selloRecepcion, selloRecibido o dentro de respuestaMH. Copia el sello real. Si no existe, deja cadena vacía; NO inventes uno.
        3. El tipoDte es el que está dentro de la identificación. Si el documento NO es un DTE, devuelve "UNKNOWN".
        4. Conserva los números originales sin inventar ni redondear.
        5. Si la información está dañada o no se puede extraer de manera confiable, deja los campos vacíos en lugar de suponer valores.
        
        Estructura requerida estricta:
        {{
            "identificacion": {{
                "codigoGeneracion": "UUID de 36 caracteres",
                 "tipoDte": "tipo DTE real, por ejemplo 01, 03, 05, 06, 07 o 14",
                "numeroControl": "DTE-...",
                "fecEmi": "YYYY-MM-DD"
            }},
            "emisor": {{
                "nombre": "Nombre de la empresa",
                "nit": "NIT de la empresa",
                "nrc": "NRC"
            }},
            "receptor": {{
                "nombre": "Nombre del receptor"
            }},
            "resumen": {{
                "totalPagar": 0.00,
                "totalCompra": 0.00,
                "subTotal": 0.00,
                "totalGravada": 0.00,
                "tributos": [
                    {{"codigo": "20", "descripcion": "IVA", "valor": 0.00}}
                ]
            }},
            "selloRecepcion": {{
                "selloRecepcion": "Cadena real del sello o cadena vacía"
            }}
        }}
        
        Texto JSON Defectuoso:
        {json_text[:8000]}
        """
        
        try:
            return self.parse_raw_to_standard(self._generate_json(prompt))
            
        except Exception as e:
            print(f"[!] Error estandarizando JSON con DeepSeek/Gemini: {e}")
            try:
                # Fallback extremo: Si la IA falla o se satura, usar el json sucio
                return json.loads(json_text)
            except:
                return {"error": "fallo_ia_json", "mensaje": str(e)}
        
    def _mock_response(self, pdf_path: str) -> dict:
        return {
            "identificacion": {
                "tipoDte": "UNKNOWN",
                "codigoGeneracion": f"GEN-FROM-OCR-{Path(pdf_path).stem}"
            },
            "emisor": {"nombre": "Emisor Detectado IA", "nit": "0000-000000-000-0"},
            "receptor": {"nombre": "Cliente Empresa SA", "nit": "1111-111111-111-1"},
            "resumen": {"totalPagar": 150.00}
        }
