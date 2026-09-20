"""Parser del estado de cuenta de Santander Enlace ("Consulta de Movimientos").

El PDF es la pantalla web impresa desde Chrome, así que debajo hay una tabla HTML:
el texto está rigurosamente alineado en columnas y los bordes de celda quedan como
`rects` en el PDF. Por eso el parser trabaja con geometría en lugar de reconstruir
el orden en que salieron los fragmentos de texto.

Dos detalles del formato que no son evidentes y que rompen los enfoques ingenuos:

- La fecha no cabe en su celda y se parte en dos renglones (`01062` + `026`), así que
  la columna Fecha se une SIN espacio mientras las demás se unen con espacio.
- Hay filas sin Referencia (las de nómina), de modo que contar posiciones de izquierda
  a derecha se desalinea. Asignar cada palabra a la banda de columna que contiene su
  centro es inmune a las celdas vacías.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from pathlib import Path

import pdfplumber

from ..core.dinero import a_centavos
from ..core.modelos import EstadoCuenta, MovimientoBancario
from ..core.texto import extraer_clabe, normalizar

TOLERANCIA_X = 1.0

_ENCABEZADOS = {
    "CUENTA": "cuenta",
    "FECHA": "fecha",
    "HORA": "hora",
    "SUCURSAL": "sucursal",
    "DESCRIPCION": "descripcion",
    "IMPORTE CARGO": "cargo",
    "IMPORTE ABONO": "abono",
    "SALDO": "saldo",
    "REFERENCIA": "referencia",
    "CONCEPTO": "concepto",
    "DESCRIPCION LARGA": "descripcion_larga",
}

_CUENTA = re.compile(r"^\d{10,}$")
_HORA = re.compile(r"^(\d{1,2}):(\d{2})$")


class PdfIlegible(RuntimeError):
    pass


def _agrupar(valores: list[float], tolerancia: float = TOLERANCIA_X) -> list[float]:
    """Colapsa coordenadas casi iguales en un solo límite de columna."""
    grupos: list[list[float]] = []
    for v in sorted(valores):
        if grupos and v - grupos[-1][-1] <= tolerancia:
            grupos[-1].append(v)
        else:
            grupos.append([v])
    return [sum(g) / len(g) for g in grupos]


def _banda(x_centro: float, limites: list[float]) -> int | None:
    for i in range(len(limites) - 1):
        if limites[i] <= x_centro < limites[i + 1]:
            return i
    return None


def _fila_de_encabezado(palabras: list[dict]) -> tuple[float, float] | None:
    """Localiza el renglón de títulos de la tabla. Devuelve (top, bottom)."""
    por_top: dict[float, list[dict]] = {}
    for w in palabras:
        por_top.setdefault(round(w["top"], 1), []).append(w)
    for top in sorted(por_top):
        textos = {normalizar(w["text"]) for w in por_top[top]}
        if {"CUENTA", "FECHA", "REFERENCIA", "CONCEPTO"} <= textos:
            return top, max(w["bottom"] for w in por_top[top])
    return None


def _columnas_de_pagina(
    pagina, palabras: list[dict]
) -> tuple[list[float], dict[int, str], float, float]:
    """Deriva los límites de columna de los bordes de celda, y los nombra con los títulos.

    Los rects del encabezado de página también existen en el PDF, así que solo se
    consideran los que están a la altura de la tabla o por debajo.
    """
    encabezado = _fila_de_encabezado(palabras)
    if encabezado is None:
        raise PdfIlegible("no se encontró el renglón de títulos de la tabla")
    top_enc, bottom_enc = encabezado

    rects = [r for r in pagina.rects if r["top"] >= top_enc - 5]
    if not rects:
        raise PdfIlegible("no se encontraron bordes de celda a la altura de la tabla")

    limites = _agrupar([r["x0"] for r in rects] + [r["x1"] for r in rects])
    if len(limites) < 5:
        raise PdfIlegible(f"solo se detectaron {len(limites)} límites de columna")

    nombres: dict[int, str] = {}
    titulos: dict[int, list[str]] = {}
    for w in palabras:
        if top_enc - 1 <= w["top"] <= top_enc + 1:
            i = _banda((w["x0"] + w["x1"]) / 2, limites)
            if i is not None:
                titulos.setdefault(i, []).append(w["text"])
    for i, partes in titulos.items():
        clave = _ENCABEZADOS.get(normalizar(" ".join(partes)))
        if clave:
            nombres[i] = clave

    faltantes = {"cuenta", "fecha", "cargo", "abono", "saldo"} - set(nombres.values())
    if faltantes:
        raise PdfIlegible(f"no se identificaron las columnas: {sorted(faltantes)}")

    fondo = max(r["bottom"] for r in rects)
    return limites, nombres, max(bottom_enc, top_enc + 1), fondo


def _celdas(bloque: list[dict], limites: list[float], nombres: dict[int, str]) -> dict[str, str]:
    """Reparte las palabras de una fila entre sus columnas."""
    por_col: dict[str, list[dict]] = {}
    for w in bloque:
        i = _banda((w["x0"] + w["x1"]) / 2, limites)
        if i is None or i not in nombres:
            continue
        por_col.setdefault(nombres[i], []).append(w)

    celdas: dict[str, str] = {}
    for col, ws in por_col.items():
        ws.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
        # La fecha viene partida a media cifra por el ancho de la celda.
        separador = "" if col == "fecha" else " "
        celdas[col] = separador.join(w["text"] for w in ws).strip()
    return celdas


def _a_movimiento(celdas: dict[str, str], pagina: int, orden: int) -> MovimientoBancario:
    crudo = celdas.get("fecha", "")
    try:
        fecha = datetime.strptime(crudo, "%d%m%Y").date()
    except ValueError as exc:
        raise PdfIlegible(f"fecha ilegible {crudo!r} en la página {pagina}") from exc

    hora = None
    if m := _HORA.match(celdas.get("hora", "")):
        hora = time(int(m.group(1)), int(m.group(2)))

    concepto = celdas.get("concepto", "")
    descripcion = celdas.get("descripcion_larga") or celdas.get("descripcion", "")

    return MovimientoBancario(
        cuenta=celdas.get("cuenta", ""),
        fecha=fecha,
        hora=hora,
        sucursal=celdas.get("sucursal") or None,
        descripcion=descripcion,
        cargo_cent=a_centavos(celdas.get("cargo", "0")),
        abono_cent=a_centavos(celdas.get("abono", "0")),
        saldo_cent=a_centavos(celdas.get("saldo", "0")),
        referencia=celdas.get("referencia") or None,
        concepto=concepto,
        clabe_ordenante=extraer_clabe(concepto),
        pagina=pagina,
        orden=orden,
    )


def _texto_encabezado(pdf) -> str:
    return "\n".join((p.extract_text() or "") for p in pdf.pages[:2])


def _buscar(patron: str, texto: str, obligatorio: bool = True) -> str | None:
    m = re.search(patron, texto, re.IGNORECASE)
    if m:
        return m.group(1)
    if obligatorio:
        raise PdfIlegible(f"no se encontró en el encabezado: {patron}")
    return None


def _fecha(texto: str) -> date:
    return datetime.strptime(texto, "%d/%m/%Y").date()


def leer_estado_cuenta(ruta: str | Path) -> EstadoCuenta:
    """Extrae los movimientos y los totales de control declarados por el banco."""
    ruta = Path(ruta)
    movimientos: list[MovimientoBancario] = []

    with pdfplumber.open(ruta) as pdf:
        cabecera = _texto_encabezado(pdf)

        for num, pagina in enumerate(pdf.pages, start=1):
            palabras = pagina.extract_words(keep_blank_chars=False, use_text_flow=False)
            if not palabras:
                continue
            try:
                limites, nombres, techo, fondo = _columnas_de_pagina(pagina, palabras)
            except PdfIlegible:
                continue  # páginas sin tabla

            col_cuenta = next(i for i, c in nombres.items() if c == "cuenta")
            datos = [w for w in palabras if techo < w["top"] < fondo]
            datos.sort(key=lambda w: (round(w["top"], 1), w["x0"]))

            bloque: list[dict] = []
            for w in datos:
                es_ancla = (
                    _banda((w["x0"] + w["x1"]) / 2, limites) == col_cuenta
                    and _CUENTA.match(w["text"]) is not None
                )
                if es_ancla:
                    if bloque:
                        movimientos.append(
                            _a_movimiento(_celdas(bloque, limites, nombres), num, len(movimientos))
                        )
                    bloque = [w]
                elif bloque:
                    bloque.append(w)
            if bloque:
                movimientos.append(
                    _a_movimiento(_celdas(bloque, limites, nombres), num, len(movimientos))
                )

    m_periodo = re.search(
        r"Periodo:\s*(\d{2}/\d{2}/\d{4})\s*al\s*(\d{2}/\d{2}/\d{4})", cabecera, re.IGNORECASE
    )
    if m_periodo is None:
        raise PdfIlegible("no se encontró el periodo en el encabezado")

    numero_abonos = _buscar(r"N[úu]mero de Abonos:\s*(\d+)", cabecera, obligatorio=False)
    numero_cargos = _buscar(r"N[úu]mero de Cargos:\s*(\d+)", cabecera, obligatorio=False)

    return EstadoCuenta(
        cuenta=_buscar(r"N[úu]mero de Cuenta:\s*(\d+)", cabecera),
        periodo_inicio=_fecha(m_periodo.group(1)),
        periodo_fin=_fecha(m_periodo.group(2)),
        saldo_inicial_cent=a_centavos(_buscar(r"Saldo Inicial:\s*\$?([\d,]+\.\d{2})", cabecera)),
        saldo_final_cent=a_centavos(_buscar(r"Saldo Final:\s*\$?([\d,]+\.\d{2})", cabecera)),
        total_movimientos_declarado=int(_buscar(r"Total de Movimientos:\s*(\d+)", cabecera)),
        total_abonos_cent_declarado=a_centavos(
            _buscar(r"Importe Total Abonos:\s*\$?([\d,]+\.\d{2})", cabecera)
        ),
        total_cargos_cent_declarado=a_centavos(
            _buscar(r"Importe Total Cargos:\s*\$?([\d,]+\.\d{2})", cabecera)
        ),
        numero_abonos_declarado=int(numero_abonos) if numero_abonos else None,
        numero_cargos_declarado=int(numero_cargos) if numero_cargos else None,
        movimientos=movimientos,
    )
