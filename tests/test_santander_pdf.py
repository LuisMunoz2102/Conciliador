"""Pruebas contra el estado de cuenta real.

Se saltan si el PDF no está disponible, porque contiene datos bancarios y no puede
vivir en el repositorio.
"""

from pathlib import Path

import pytest

from conciliador.ingesta.santander_pdf import leer_estado_cuenta

PDF = Path(
    r"C:\Users\luis_\OneDrive\Escritorio\Descarga Comprobantes\SANTANDER BDB LOG AL 23-06 - .pdf"
)

pytestmark = pytest.mark.skipif(not PDF.exists(), reason="estado de cuenta no disponible")


@pytest.fixture(scope="module")
def estado():
    return leer_estado_cuenta(PDF)


def test_encabezado(estado):
    assert estado.cuenta == "65509574438"
    assert estado.periodo_inicio.isoformat() == "2026-06-01"
    assert estado.periodo_fin.isoformat() == "2026-06-23"


def test_extrae_todos_los_movimientos(estado):
    assert len(estado.movimientos) == estado.total_movimientos_declarado == 183


def test_los_importes_cuadran_con_los_totales_de_control(estado):
    assert sum(m.abono_cent for m in estado.abonos) == estado.total_abonos_cent_declarado
    assert sum(m.cargo_cent for m in estado.cargos) == estado.total_cargos_cent_declarado


def test_cuenta_abonos_y_cargos(estado):
    assert len(estado.abonos) == 9
    assert len(estado.cargos) == 174


def test_la_fecha_partida_en_dos_renglones_se_reconstruye(estado):
    """La celda es angosta y el banco parte '01062026' en '01062' + '026'."""
    assert all(m.fecha.year == 2026 and m.fecha.month == 6 for m in estado.movimientos)


def test_extrae_la_clabe_ordenante(estado):
    tef = [m for m in estado.abonos if m.concepto.startswith("FCS")]
    assert len(tef) == 3
    assert {m.clabe_ordenante for m in tef} == {"021180040573182974"}


def test_el_concepto_no_se_mezcla_con_la_descripcion(estado):
    mayor = max(estado.abonos, key=lambda m: m.abono_cent)
    assert mayor.descripcion == "ABONO TRANSFERENCIA SPEI"
    assert mayor.concepto == "ADVANCE - FUNDING SOURCE - TWCF 0800065"


def test_filas_sin_referencia_no_desalinean_las_columnas(estado):
    """Las filas de nómina no traen Referencia; el importe debe quedar en su columna."""
    nomina = [m for m in estado.cargos if "NOMINA" in m.descripcion.upper()]
    assert nomina
    assert all(m.cargo_cent > 0 and m.abono_cent == 0 for m in nomina)
