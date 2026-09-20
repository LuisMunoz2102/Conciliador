"""Prueba de extremo a extremo con los archivos reales de septiembre 2026."""

from pathlib import Path

import pytest

from conciliador.ingesta.facturas_excel import leer_facturas
from conciliador.ingesta.santander_pdf import leer_estado_cuenta
from conciliador.ingesta.validacion import exigir_validez, validar
from conciliador.motor.cascada import conciliar
from conciliador.reglas.esquema import cargar_reglas
from conciliador.reporte.excel import generar

RAIZ = Path(__file__).resolve().parents[1]
PDF = RAIZ / "datos" / "SANTANDER BDB LOG AL 18-09.pdf"
XLSX = RAIZ / "datos" / "Para conciliar.xlsx"

pytestmark = pytest.mark.skipif(
    not (PDF.exists() and XLSX.exists()), reason="insumos reales no disponibles"
)


@pytest.fixture(scope="module")
def resultado():
    estado = leer_estado_cuenta(PDF)
    validar(estado)
    exigir_validez(estado)
    return conciliar(estado, leer_facturas(XLSX), cargar_reglas(RAIZ / "config" / "clientes.yaml"))


def test_cada_peso_queda_clasificado(resultado):
    """La suma de las categorías tiene que dar el total de abonos del banco."""
    suma = sum(d.movimiento.abono_cent for d in resultado.depositos)
    assert suma == resultado.estado_cuenta.total_abonos_cent_declarado


def test_identifica_los_cobros_de_amazon_por_importe_exacto(resultado):
    amazon = [
        d for d in resultado.depositos
        if d.contraparte.rfc == "ANE140618P37" and d.facturas
    ]
    assert len(amazon) == 3
    for d in amazon:
        assert d.movimiento.abono_cent == d.facturas[0].total_cent


def test_resuelve_el_factoraje_neto_de_comision(resultado):
    """Dos depósitos TWCF corresponden a facturas de 128,783.20 con ~1.15% de comisión."""
    unicos = [
        d for d in resultado.depositos
        if d.contraparte.tipo.value == "FACTOR" and d.estado.value == "REVISAR"
    ]
    assert len(unicos) == 2
    for d in unicos:
        comision = 1 - d.movimiento.abono_cent / d.facturas[0].total_cent
        assert 0.010 < comision < 0.013


def test_el_deposito_ambiguo_no_se_concilia_pero_rescata_lo_cierto(resultado):
    """8,690,705.47 admite varias combinaciones; solo BDB-790 está en todas."""
    ambiguos = [d for d in resultado.depositos if d.estado.value == "AMBIGUO"]
    assert len(ambiguos) == 1
    d = ambiguos[0]
    assert len(d.alternativas) > 1
    assert [f.referencia for f in d.facturas] == ["BDB790"]


def test_descarta_la_devolucion_como_cobro(resultado):
    devolucion = [d for d in resultado.depositos if "DEVOLUCION" in d.movimiento.concepto.upper()]
    assert len(devolucion) == 1
    assert devolucion[0].estado.value == "RUIDO BANCARIO"
    assert not devolucion[0].facturas


def test_genera_el_reporte(resultado, tmp_path):
    destino = generar(resultado, tmp_path / "reporte.xlsx")
    assert destino.exists() and destino.stat().st_size > 5000
