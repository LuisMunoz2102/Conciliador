"""Validación del estado de cuenta contra los totales que el propio banco declara.

Si el parser perdió, duplicó o desalineó una fila, un reporte de conciliación
construido encima sería peor que no tener reporte: el contador firmaría algo que
nadie revisó. Por eso las validaciones críticas detienen el proceso.
"""

from __future__ import annotations

from ..core.dinero import formatear
from ..core.modelos import EstadoCuenta, Validacion


class EstadoCuentaInconsistente(RuntimeError):
    pass


def _cmp(nombre: str, esperado, obtenido, critica: bool = True) -> Validacion:
    return Validacion(
        nombre=nombre,
        esperado=str(esperado),
        obtenido=str(obtenido),
        ok=esperado == obtenido,
        critica=critica,
    )


def validar(estado: EstadoCuenta) -> list[Validacion]:
    movs = estado.movimientos
    pruebas: list[Validacion] = [
        _cmp("Número de movimientos", estado.total_movimientos_declarado, len(movs)),
        _cmp(
            "Importe total de abonos",
            formatear(estado.total_abonos_cent_declarado),
            formatear(sum(m.abono_cent for m in movs)),
        ),
        _cmp(
            "Importe total de cargos",
            formatear(estado.total_cargos_cent_declarado),
            formatear(sum(m.cargo_cent for m in movs)),
        ),
    ]

    if estado.numero_abonos_declarado is not None:
        pruebas.append(_cmp("Número de abonos", estado.numero_abonos_declarado, len(estado.abonos)))
    if estado.numero_cargos_declarado is not None:
        pruebas.append(_cmp("Número de cargos", estado.numero_cargos_declarado, len(estado.cargos)))

    if movs:
        pruebas.append(
            _cmp(
                "Saldo final",
                formatear(estado.saldo_final_cent),
                formatear(movs[-1].saldo_cent),
            )
        )

    pruebas.append(_validar_saldo_corriente(estado))

    # El encabezado de Santander puede declarar un Saldo Inicial que no cuadra con
    # sus propios movimientos. Se reporta, pero no detiene el proceso: la columna de
    # saldo fila por fila es la que manda, y es consistente.
    if movs:
        derivado = movs[0].saldo_cent - movs[0].abono_cent + movs[0].cargo_cent
        pruebas.append(
            _cmp(
                "Saldo inicial declarado vs. implícito en los movimientos",
                formatear(estado.saldo_inicial_cent),
                formatear(derivado),
                critica=False,
            )
        )

    estado.validaciones = pruebas
    return pruebas


def _validar_saldo_corriente(estado: EstadoCuenta) -> Validacion:
    """Comprueba que cada saldo sea el anterior más el abono menos el cargo.

    A diferencia de los totales agregados, esta prueba señala en qué fila empezó el
    problema, y detecta errores que se compensan entre sí y que los totales no ven.
    """
    movs = estado.movimientos
    for i in range(1, len(movs)):
        esperado = movs[i - 1].saldo_cent + movs[i].abono_cent - movs[i].cargo_cent
        if esperado != movs[i].saldo_cent:
            m = movs[i]
            return Validacion(
                nombre="Saldo corriente fila por fila",
                esperado=f"fila {i} (pág. {m.pagina}): {formatear(esperado)}",
                obtenido=f"{formatear(m.saldo_cent)} — {m.fecha:%d/%m/%Y} {m.descripcion[:40]}",
                ok=False,
            )
    return Validacion(
        nombre="Saldo corriente fila por fila",
        esperado=f"{max(len(movs) - 1, 0)} transiciones consistentes",
        obtenido=f"{max(len(movs) - 1, 0)} transiciones consistentes",
        ok=True,
    )


def exigir_validez(estado: EstadoCuenta) -> None:
    fallas = [v for v in estado.validaciones if v.critica and not v.ok]
    if fallas:
        detalle = "\n".join(f"  - {v.nombre}: esperado {v.esperado}, obtenido {v.obtenido}" for v in fallas)
        raise EstadoCuentaInconsistente(
            "El estado de cuenta no cuadra con los totales que declara el banco.\n"
            f"{detalle}\n"
            "No se genera reporte: conciliar sobre datos incompletos produce cifras falsas."
        )
