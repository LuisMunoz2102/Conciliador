"""Cascada de reglas, de mayor a menor confianza.

Cada factura asignada sale del pool, y las reglas corren en orden fijo, de modo que
el resultado es explicable y reproducible: siempre se puede decir por qué una factura
quedó ligada a un depósito.

El factoraje se aparta antes que el cruce por monto. Si no, el motor intentaría casar
un adelanto de varios millones contra facturas sueltas y produciría combinaciones
espurias que se ven convincentes y no significan nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.dinero import formatear
from ..core.modelos import (
    Comprobante,
    Estado,
    EstadoCuenta,
    MovimientoBancario,
    Regla,
)
from ..reglas.esquema import Contraparte, Reglas, TipoContraparte, resolver
from .subconjunto import buscar, interseccion, rango_por_comision


@dataclass
class ResultadoDeposito:
    movimiento: MovimientoBancario
    contraparte: Contraparte
    estado: Estado
    regla: Regla = Regla.SIN_REGLA
    confianza: int = 0
    facturas: list[Comprobante] = field(default_factory=list)
    alternativas: list[list[Comprobante]] = field(default_factory=list)
    diferencia_cent: int = 0
    explicacion: str = ""

    @property
    def importe_facturas_cent(self) -> int:
        return sum(f.total_cent for f in self.facturas)


@dataclass
class Resultado:
    estado_cuenta: EstadoCuenta
    facturas: list[Comprobante]
    depositos: list[ResultadoDeposito]

    @property
    def conciliadas(self) -> list[Comprobante]:
        """Facturas con cobro identificado.

        Incluye las de los depósitos ambiguos, porque ahí `facturas` solo contiene
        la intersección de todas las combinaciones posibles: son las únicas de las
        que se puede afirmar el cobro con certeza.
        """
        vistas: list[Comprobante] = []
        for d in self.depositos:
            vistas.extend(d.facturas)
        return vistas

    @property
    def por_cobrar(self) -> list[Comprobante]:
        cobradas = {f.uuid for f in self.conciliadas}
        return [
            f
            for f in self.facturas
            if not f.marcada_cobrada and f.uuid not in cobradas and not f.es_nota_credito
        ]


def _en_ventana(f: Comprobante, mov: MovimientoBancario, reglas: Reglas) -> bool:
    dias = (mov.fecha - f.fecha_emision).days
    return -reglas.defaults.ventana_dias_despues <= dias <= reglas.defaults.ventana_dias_antes


def _candidatas(
    facturas: list[Comprobante],
    mov: MovimientoBancario,
    reglas: Reglas,
    rfcs: set[str] | None,
    solo_pendientes: bool = True,
) -> list[Comprobante]:
    """Facturas que este depósito podría estar pagando.

    Por omisión excluye las que ya están marcadas como cobradas: si una factura ya
    se cobró, no puede ser la que explica un depósito posterior, y dejarla en el
    pool multiplica las combinaciones falsas hasta volver inútil la búsqueda.
    """
    return [
        f
        for f in facturas
        if f.total_cent > 0
        and not f.es_nota_credito
        and _en_ventana(f, mov, reglas)
        and (rfcs is None or f.rfc_receptor in rfcs)
        and not (solo_pendientes and f.marcada_cobrada)
    ]


def _describir(facturas: list[Comprobante]) -> str:
    return ", ".join(f.referencia for f in facturas)


def conciliar(
    estado_cuenta: EstadoCuenta, facturas: list[Comprobante], reglas: Reglas
) -> Resultado:
    disponibles = list(facturas)
    resultados: list[ResultadoDeposito] = []

    for mov in sorted(estado_cuenta.abonos, key=lambda m: (m.fecha, m.orden)):
        contraparte = resolver(mov, reglas)

        if contraparte.tipo is TipoContraparte.RUIDO:
            resultados.append(
                ResultadoDeposito(
                    movimiento=mov,
                    contraparte=contraparte,
                    estado=Estado.RUIDO,
                    regla=Regla.R5_RUIDO,
                    confianza=100,
                    explicacion=contraparte.detalle or "No es un cobro a clientes.",
                )
            )
            continue

        if contraparte.tipo is TipoContraparte.FACTOR:
            resultados.append(_factoraje(mov, contraparte, disponibles, reglas))
        else:
            resultados.append(_cobro_directo(mov, contraparte, disponibles, reglas))

        for f in resultados[-1].facturas:
            if f in disponibles:
                disponibles.remove(f)

    return Resultado(estado_cuenta=estado_cuenta, facturas=facturas, depositos=resultados)


def _cobro_directo(
    mov: MovimientoBancario,
    contraparte: Contraparte,
    disponibles: list[Comprobante],
    reglas: Reglas,
) -> ResultadoDeposito:
    rfcs = {contraparte.rfc} if contraparte.rfc else None
    candidatas = _candidatas(disponibles, mov, reglas, rfcs)

    def _exactas(pool: list[Comprobante]) -> list[Comprobante]:
        return [f for f in pool if mov.abono_cent in (f.total_cent, f.monto_cobrable_cent)]

    exactas = _exactas(candidatas)
    if not exactas:
        # Si ninguna pendiente coincide, puede tratarse de una que ya estaba marcada:
        # vale la pena decirlo en lugar de reportar el depósito como no identificado.
        exactas = _exactas(_candidatas(disponibles, mov, reglas, rfcs, solo_pendientes=False))
    if len(exactas) == 1:
        f = exactas[0]
        nota = " (ya marcada como cobrada)" if f.marcada_cobrada else ""
        return ResultadoDeposito(
            movimiento=mov,
            contraparte=contraparte,
            estado=Estado.AUTO,
            regla=Regla.R1_EXACTO,
            confianza=95,
            facturas=[f],
            explicacion=f"Importe idéntico a la factura {f.referencia} del "
            f"{f.fecha_emision:%d/%m/%Y}{nota}.",
        )
    if len(exactas) > 1:
        return ResultadoDeposito(
            movimiento=mov,
            contraparte=contraparte,
            estado=Estado.AMBIGUO,
            regla=Regla.R1_EXACTO,
            alternativas=[[f] for f in exactas],
            explicacion=f"{len(exactas)} facturas tienen exactamente este importe: "
            f"{_describir(exactas)}. Se requiere decisión manual.",
        )

    if contraparte.tipo is TipoContraparte.DESCONOCIDA:
        return ResultadoDeposito(
            movimiento=mov,
            contraparte=contraparte,
            estado=Estado.SIN_MATCH,
            explicacion="No hay regla que identifique el origen de este depósito. "
            "Agrégalo a config/clientes.yaml.",
        )

    montos = [f.total_cent for f in candidatas]
    hallazgo = buscar(montos, mov.abono_cent, mov.abono_cent)
    return _desde_busqueda(
        mov, contraparte, candidatas, hallazgo, Regla.R2_SUBCONJUNTO, 85, comision=None
    )


def _factoraje(
    mov: MovimientoBancario,
    contraparte: Contraparte,
    disponibles: list[Comprobante],
    reglas: Reglas,
) -> ResultadoDeposito:
    factor = next((f for f in reglas.factores if f.id == contraparte.id), None)
    rfcs = set(factor.financia_a) if factor and factor.financia_a else None
    # El factor no puede adelantar una factura que todavía no se emite, así que aquí
    # no aplica la tolerancia de días posteriores que sí tiene un cobro directo.
    candidatas = [
        f for f in _candidatas(disponibles, mov, reglas, rfcs) if f.fecha_emision <= mov.fecha
    ]

    if factor is None:
        return ResultadoDeposito(
            movimiento=mov, contraparte=contraparte, estado=Estado.FACTORAJE,
            regla=Regla.R4_FACTORAJE,
            explicacion="Depósito de factoraje sin configuración de comisión.",
        )

    minimo, maximo = rango_por_comision(mov.abono_cent, factor.comision_min, factor.comision_max)
    hallazgo = buscar([f.total_cent for f in candidatas], minimo, maximo)
    return _desde_busqueda(
        mov, contraparte, candidatas, hallazgo, Regla.R4_FACTORAJE, 75, comision=True
    )


def _desde_busqueda(
    mov: MovimientoBancario,
    contraparte: Contraparte,
    candidatas: list[Comprobante],
    hallazgo,
    regla: Regla,
    confianza: int,
    comision: bool | None,
) -> ResultadoDeposito:
    if not hallazgo.soluciones:
        estado = Estado.FACTORAJE if regla is Regla.R4_FACTORAJE else Estado.SIN_MATCH
        return ResultadoDeposito(
            movimiento=mov, contraparte=contraparte, estado=estado, regla=regla,
            explicacion="Ninguna combinación de facturas pendientes explica este depósito. "
            "Hace falta el detalle de la remesa."
            if regla is Regla.R4_FACTORAJE
            else "Ninguna combinación de facturas explica este importe.",
        )

    def _facturas(indices) -> list[Comprobante]:
        return sorted((candidatas[i] for i in indices), key=lambda f: f.fecha_emision)

    if hallazgo.unica:
        elegidas = _facturas(hallazgo.soluciones[0])
        bruto = sum(f.total_cent for f in elegidas)
        detalle = f"Suma de {len(elegidas)} factura(s): {_describir(elegidas)}"
        if comision:
            pct = (1 - mov.abono_cent / bruto) * 100
            detalle += f". Importe bruto {formatear(bruto)}, comisión implícita {pct:.3f}%"
        return ResultadoDeposito(
            movimiento=mov, contraparte=contraparte,
            estado=Estado.REVISAR if comision else Estado.AUTO,
            regla=regla, confianza=confianza, facturas=elegidas,
            diferencia_cent=bruto - mov.abono_cent, explicacion=detalle + ".",
        )

    ciertas = _facturas(interseccion(hallazgo.soluciones))
    alternativas = [_facturas(s) for s in hallazgo.soluciones[:8]]
    partes = [f"Hay {len(hallazgo.soluciones)} combinaciones posibles"]
    if hallazgo.truncada:
        partes[0] += " (o más)"
    if ciertas:
        partes.append(
            f"pero {_describir(ciertas)} aparece en todas, así que ese cobro es seguro. "
            f"El resto necesita el detalle de la remesa"
        )
    else:
        partes.append("sin ninguna factura común a todas. Elegir una sería inventar el dato")
    return ResultadoDeposito(
        movimiento=mov, contraparte=contraparte, estado=Estado.AMBIGUO, regla=regla,
        confianza=40 if ciertas else 0, facturas=ciertas, alternativas=alternativas,
        explicacion=". ".join(partes) + ".",
    )
