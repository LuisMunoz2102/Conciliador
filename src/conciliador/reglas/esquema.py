"""Carga y validación del archivo de reglas, y resolución de concepto a contraparte."""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from ..core.modelos import MovimientoBancario
from ..core.texto import normalizar


class TipoContraparte(str, Enum):
    RUIDO = "RUIDO"
    FACTOR = "FACTOR"
    CLIENTE = "CLIENTE"
    DESCONOCIDA = "DESCONOCIDA"


class ReglaRuido(BaseModel):
    id: str
    patron: str
    etiqueta: str = ""


class ReglaFactor(BaseModel):
    id: str
    nombre: str
    patrones: list[str] = Field(default_factory=list)
    captura_lote: str | None = None
    comision_min: float = 0.0
    comision_max: float = 0.03
    financia_a: list[str] = Field(default_factory=list)


class ReglaCliente(BaseModel):
    rfc: str
    nombre: str
    clabe_ordenante: list[str] = Field(default_factory=list)
    patrones: list[str] = Field(default_factory=list)
    notas: str = ""


class Defaults(BaseModel):
    ventana_dias_antes: int = 120
    ventana_dias_despues: int = 3
    tolerancia_centavos: int = 0


class Reglas(BaseModel):
    version: int = 1
    defaults: Defaults = Field(default_factory=Defaults)
    ruido: list[ReglaRuido] = Field(default_factory=list)
    factores: list[ReglaFactor] = Field(default_factory=list)
    clientes: list[ReglaCliente] = Field(default_factory=list)


class Contraparte(BaseModel):
    tipo: TipoContraparte
    id: str = ""
    nombre: str = ""
    rfc: str = ""
    lote: str | None = None
    detalle: str = ""


def cargar_reglas(ruta: str | Path) -> Reglas:
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"no se encontró el archivo de reglas: {ruta}")
    with ruta.open("r", encoding="utf-8") as fh:
        return Reglas.model_validate(yaml.safe_load(fh) or {})


def _coincide(patrones: list[str], texto: str) -> bool:
    return any(re.search(p, texto, re.IGNORECASE) for p in patrones)


def resolver(mov: MovimientoBancario, reglas: Reglas) -> Contraparte:
    """Identifica quién originó un depósito.

    La CLABE ordenante va primero porque es determinista; el texto del concepto
    depende de cómo lo haya capturado el banco que envió el dinero.
    """
    concepto = normalizar(mov.concepto)
    descripcion = normalizar(mov.descripcion)
    ambos = f"{descripcion} {concepto}"

    for r in reglas.ruido:
        if re.search(r.patron, ambos, re.IGNORECASE):
            return Contraparte(
                tipo=TipoContraparte.RUIDO, id=r.id, nombre=r.etiqueta or r.id, detalle=r.etiqueta
            )

    if mov.clabe_ordenante:
        for c in reglas.clientes:
            if mov.clabe_ordenante in c.clabe_ordenante:
                return Contraparte(
                    tipo=TipoContraparte.CLIENTE,
                    id=c.rfc,
                    nombre=c.nombre,
                    rfc=c.rfc,
                    detalle=f"CLABE ordenante {mov.clabe_ordenante}",
                )

    for f in reglas.factores:
        if _coincide(f.patrones, concepto):
            lote = None
            if f.captura_lote and (m := re.search(f.captura_lote, mov.concepto, re.IGNORECASE)):
                lote = m.group(1)
            return Contraparte(
                tipo=TipoContraparte.FACTOR,
                id=f.id,
                nombre=f.nombre,
                lote=lote,
                detalle=f"lote {lote}" if lote else "",
            )

    for c in reglas.clientes:
        if _coincide(c.patrones, concepto):
            return Contraparte(
                tipo=TipoContraparte.CLIENTE, id=c.rfc, nombre=c.nombre, rfc=c.rfc,
                detalle="patrón de concepto",
            )

    return Contraparte(tipo=TipoContraparte.DESCONOCIDA, nombre="Sin identificar")
