"""Normalización de texto y extracción de los identificadores que trae el concepto bancario."""

from __future__ import annotations

import re
import unicodedata

_ESPACIOS = re.compile(r"\s+")
_CLABE = re.compile(r"(?<!\d)(\d{18})(?!\d)")
_RFC = re.compile(r"\b([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b")


def normalizar(texto: str | None) -> str:
    """Mayúsculas, sin acentos y con los espacios colapsados.

    El banco imprime padding irregular ('TWCF   0800065'), así que comparar sin
    normalizar produce fallos de coincidencia difíciles de diagnosticar.
    """
    if not texto:
        return ""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return _ESPACIOS.sub(" ", sin_acentos).strip().upper()


def extraer_clabe(concepto: str | None) -> str | None:
    """La CLABE ordenante identifica la cuenta que envió el dinero.

    Es determinista, a diferencia de cómo se haya escrito el concepto, así que
    es el primer criterio para resolver a qué contraparte pertenece un depósito.
    """
    if not concepto:
        return None
    m = _CLABE.search(concepto)
    return m.group(1) if m else None


def extraer_rfc(concepto: str | None) -> str | None:
    """Los cargos a proveedores traen 'RFC XXXX' en el concepto; los abonos casi nunca."""
    if not concepto:
        return None
    m = _RFC.search(normalizar(concepto))
    return m.group(1) if m else None
