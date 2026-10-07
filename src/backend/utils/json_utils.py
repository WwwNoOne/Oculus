"""Utilidades para leer JSONs de DTE con estructuras variables.

Los DTE pueden venir como documentos directos (con clave "identificacion"),
anidados dentro de respuestas (p. ej. "detalleDTE", "respuesta") o con
variantes de nombres. Estas funciones buscan de forma tolerante sin
levantar excepciones.
"""


def find_section(data, name):
    """Busca recursivamente una seccion (dict) por nombre. Retorna {} si no existe."""
    if isinstance(data, dict):
        value = data.get(name)
        if isinstance(value, dict) and value:
            return value
        for item in data.values():
            found = find_section(item, name)
            if isinstance(found, dict) and found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_section(item, name)
            if isinstance(found, dict) and found:
                return found
    return {}


def extract_identificacion(data):
    """Obtiene la identificacion tanto de DTE directos como de respuestas anidadas."""
    if not isinstance(data, dict):
        return {}
    ident = data.get("identificacion")
    if isinstance(ident, dict) and ident:
        return ident
    found = find_section(data, "identificacion")
    return found if isinstance(found, dict) else {}


def get_document_sections(data, section):
    """Obtiene una seccion (emisor, resumen, selloRecepcion...) del documento.

    Tambien resuelve documentos envueltos en "detalleDTE".
    """
    if not isinstance(data, dict):
        return {}
    direct = data.get(section)
    if isinstance(direct, dict) and direct:
        return direct
    detalle = data.get("detalleDTE")
    if isinstance(detalle, dict):
        nested = detalle.get(section)
        if isinstance(nested, dict) and nested:
            return nested
    found = find_section(data, section)
    return found if isinstance(found, dict) else {}


def _first_non_empty_string(*values):
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_sello(data):
    """Extrae el sello de recepcion aceptando variantes de nombre. Retorna "" si no existe."""
    if not isinstance(data, dict):
        return ""
    for key in ("selloRecepcion", "selloRecibido", "sello"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            found = _first_non_empty_string(
                value.get("selloRecepcion"),
                value.get("selloRecibido"),
                value.get("sello"),
                value.get("valor"),
            )
            if found:
                return found
    for key in ("selloRecepcion", "selloRecibido"):
        section = find_section(data, key)
        if isinstance(section, dict):
            found = _first_non_empty_string(
                section.get("selloRecepcion"),
                section.get("selloRecibido"),
                section.get("sello"),
                section.get("valor"),
            )
            if found:
                return found
    return ""


def get_sello_from_mh_response(data):
    """Extrae el sello desde la respuesta del Ministerio de Hacienda, si existe."""
    if not isinstance(data, dict):
        return ""
    for container_key in ("respuestaMH", "respuesta", "mhResponse"):
        container = data.get(container_key)
        if isinstance(container, dict):
            found = _first_non_empty_string(
                container.get("selloRecibido"),
                container.get("selloRecepcion"),
                container.get("sello"),
            )
            if found:
                return found
    mh_section = find_section(data, "respuestaMH")
    if isinstance(mh_section, dict):
        found = _first_non_empty_string(
            mh_section.get("selloRecibido"),
            mh_section.get("selloRecepcion"),
            mh_section.get("sello"),
        )
        if found:
            return found
    return ""
