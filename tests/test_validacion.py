from datetime import date

import pytest

from conciliador.core.modelos import EstadoCuenta, MovimientoBancario
from conciliador.ingesta.validacion import (
    EstadoCuentaInconsistente,
    exigir_validez,
    validar,
)


def _movimiento(orden: int, abono: int, cargo: int, saldo: int) -> MovimientoBancario:
    return MovimientoBancario(
        cuenta="65509574438",
        fecha=date(2026, 6, 1),
        descripcion="PRUEBA",
        cargo_cent=cargo,
        abono_cent=abono,
        saldo_cent=saldo,
        orden=orden,
    )


def _estado(movimientos: list[MovimientoBancario], **ajustes) -> EstadoCuenta:
    base = dict(
        cuenta="65509574438",
        periodo_inicio=date(2026, 6, 1),
        periodo_fin=date(2026, 6, 23),
        saldo_inicial_cent=100_000,
        saldo_final_cent=movimientos[-1].saldo_cent if movimientos else 100_000,
        total_movimientos_declarado=len(movimientos),
        total_abonos_cent_declarado=sum(m.abono_cent for m in movimientos),
        total_cargos_cent_declarado=sum(m.cargo_cent for m in movimientos),
        movimientos=movimientos,
    )
    base.update(ajustes)
    return EstadoCuenta(**base)


def test_estado_consistente_pasa_todas_las_criticas():
    movs = [
        _movimiento(0, 50_000, 0, 150_000),
        _movimiento(1, 0, 20_000, 130_000),
    ]
    estado = _estado(movs)
    validar(estado)
    assert estado.valido
    exigir_validez(estado)


def test_detecta_fila_perdida_por_los_totales():
    movs = [_movimiento(0, 50_000, 0, 150_000)]
    estado = _estado(movs, total_movimientos_declarado=2)
    validar(estado)
    assert not estado.valido
    with pytest.raises(EstadoCuentaInconsistente):
        exigir_validez(estado)


def test_el_saldo_corriente_señala_la_fila_del_problema():
    movs = [
        _movimiento(0, 50_000, 0, 150_000),
        _movimiento(1, 0, 20_000, 999_999),  # saldo incongruente
    ]
    estado = _estado(movs, saldo_final_cent=999_999)
    validar(estado)
    prueba = next(v for v in estado.validaciones if v.nombre.startswith("Saldo corriente"))
    assert not prueba.ok
    assert "fila 1" in prueba.esperado


def test_saldo_inicial_declarado_inconsistente_no_detiene_el_proceso():
    """Santander declara un Saldo Inicial que no cuadra con sus propios movimientos.

    Ocurre en el estado de junio 2026: el encabezado dice 2,355,317.34 y los
    movimientos implican 2,355,317.30. La columna de saldo es la que manda.
    """
    movs = [_movimiento(0, 4, 0, 150_000)]
    estado = _estado(movs, saldo_inicial_cent=150_000)
    validar(estado)
    prueba = next(v for v in estado.validaciones if "Saldo inicial" in v.nombre)
    assert not prueba.ok
    assert not prueba.critica
    assert estado.valido
    exigir_validez(estado)
