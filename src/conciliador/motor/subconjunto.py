"""Búsqueda de combinaciones de facturas que expliquen un depósito.

El problema es de suma de subconjuntos, que es NP-completo, así que la búsqueda va
acotada por candidatas, cardinalidad, número de soluciones y tiempo. Con tarifas de
flete que se repiten es normal que varias combinaciones sumen lo mismo, de modo que
encontrar *una* solución no significa haber encontrado *la* solución.

De ahí `interseccion`: cuando hay varias respuestas posibles, las facturas que
aparecen en todas ellas son las únicas de las que se puede afirmar algo con certeza.
Es información real aunque el resto siga ambiguo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence, TypeVar

T = TypeVar("T")

MAX_CANDIDATAS = 22
MAX_CARDINALIDAD = 6
MAX_SOLUCIONES = 200
SEGUNDOS_LIMITE = 5.0


@dataclass
class Busqueda:
    soluciones: list[tuple[int, ...]]
    truncada: bool
    candidatas_consideradas: int

    @property
    def unica(self) -> bool:
        return len(self.soluciones) == 1 and not self.truncada

    @property
    def ambigua(self) -> bool:
        return len(self.soluciones) > 1


def buscar(
    montos: Sequence[int],
    minimo: int,
    maximo: int,
    max_cardinalidad: int = MAX_CARDINALIDAD,
    max_soluciones: int = MAX_SOLUCIONES,
    segundos: float = SEGUNDOS_LIMITE,
) -> Busqueda:
    """Encuentra los subconjuntos de `montos` cuya suma cae en [minimo, maximo].

    Devuelve índices sobre la secuencia original. Para un objetivo puntual se pasa
    el mismo valor como mínimo y máximo.
    """
    indices = [i for i, m in enumerate(montos) if 0 < m <= maximo]
    indices.sort(key=lambda i: montos[i], reverse=True)
    truncada = len(indices) > MAX_CANDIDATAS
    indices = indices[:MAX_CANDIDATAS]

    # Sufijos para podar: si ni sumando todo lo que queda se alcanza el mínimo, se corta.
    restante = [0] * (len(indices) + 1)
    for i in range(len(indices) - 1, -1, -1):
        restante[i] = restante[i + 1] + montos[indices[i]]

    soluciones: list[tuple[int, ...]] = []
    limite = time.monotonic() + segundos
    agotado = False

    def explorar(pos: int, suma: int, elegidos: list[int]) -> None:
        nonlocal agotado
        if agotado or len(soluciones) >= max_soluciones:
            return
        if time.monotonic() > limite:
            agotado = True
            return
        if minimo <= suma <= maximo and elegidos:
            soluciones.append(tuple(elegidos))
            return  # agregar más facturas solo se pasaría del máximo
        if pos >= len(indices) or suma > maximo or len(elegidos) >= max_cardinalidad:
            return
        if suma + restante[pos] < minimo:
            return
        for i in range(pos, len(indices)):
            if suma + restante[i] < minimo:
                break
            elegidos.append(indices[i])
            explorar(i + 1, suma + montos[indices[i]], elegidos)
            elegidos.pop()
            if agotado or len(soluciones) >= max_soluciones:
                return

    explorar(0, 0, [])
    return Busqueda(
        soluciones=soluciones,
        truncada=truncada or agotado or len(soluciones) >= max_soluciones,
        candidatas_consideradas=len(indices),
    )


def interseccion(soluciones: list[tuple[int, ...]]) -> set[int]:
    """Índices presentes en todas las soluciones: lo único afirmable con certeza."""
    if not soluciones:
        return set()
    comun = set(soluciones[0])
    for s in soluciones[1:]:
        comun &= set(s)
    return comun


def rango_por_comision(objetivo: int, comision_min: float, comision_max: float) -> tuple[int, int]:
    """Importe bruto que, neto de comisión, produce el depósito observado."""
    bruto_min = int(round(objetivo / (1 - comision_min)))
    bruto_max = int(round(objetivo / (1 - comision_max)))
    return min(bruto_min, bruto_max), max(bruto_min, bruto_max)
