"""Importes en centavos enteros. Decimal solo en las fronteras de lectura y escritura."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_LIMPIEZA = re.compile(r"[\s$,]|MXN|USD|EUR")
_IMPORTE = re.compile(r"^-?\d{1,3}(,\d{3})*\.\d{2}$|^-?\d+\.\d{2}$")


class ImporteInvalido(ValueError):
    pass


def parece_importe(texto: str) -> bool:
    """Reconoce el formato con el que el banco imprime los importes: 1,234.56"""
    return bool(_IMPORTE.match(texto.strip()))


def a_centavos(texto: str | Decimal | int | float | None) -> int:
    """Convierte a centavos enteros. Acepta '$1,234.56 MXN', Decimal o number."""
    if texto is None or texto == "":
        return 0
    if isinstance(texto, int):
        return texto * 100
    if isinstance(texto, (Decimal, float)):
        return int((Decimal(str(texto)) * 100).quantize(Decimal("1")))

    limpio = _LIMPIEZA.sub("", str(texto))
    if limpio in ("", "-"):
        return 0
    try:
        return int((Decimal(limpio) * 100).quantize(Decimal("1")))
    except InvalidOperation as exc:
        raise ImporteInvalido(f"no es un importe reconocible: {texto!r}") from exc


def a_decimal(centavos: int) -> Decimal:
    return Decimal(centavos) / 100


def formatear(centavos: int) -> str:
    return f"{a_decimal(centavos):,.2f}"
