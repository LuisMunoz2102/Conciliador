from decimal import Decimal

import pytest

from conciliador.core.dinero import a_centavos, formatear, parece_importe
from conciliador.core.texto import extraer_clabe, extraer_rfc, normalizar


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("0.00", 0),
        ("0.04", 4),
        ("1,234.56", 123456),
        ("6,710,517.43", 671051743),
        ("$15,962,895.11 MXN", 1596289511),
        ("-90.00", -9000),
        ("", 0),
        (None, 0),
    ],
)
def test_a_centavos(texto, esperado):
    assert a_centavos(texto) == esperado


def test_a_centavos_desde_decimal():
    assert a_centavos(Decimal("25023.20")) == 2502320


def test_los_nueve_abonos_suman_el_total_de_control():
    """El PDF declara 'Importe Total Abonos: $15,962,895.11'. En centavos debe cuadrar exacto."""
    abonos = [
        "0.04",
        "303,602.11",
        "199,508.39",
        "6,710,517.43",
        "1,635,374.76",
        "129,436.32",
        "228,204.36",
        "281,186.32",
        "6,475,065.38",
    ]
    assert sum(a_centavos(a) for a in abonos) == a_centavos("15,962,895.11")


def test_formatear():
    assert formatear(1596289511) == "15,962,895.11"


@pytest.mark.parametrize(
    "texto,esperado",
    [("1,234.56", True), ("0.00", True), ("0560", False), ("SPEI", False), ("01:16", False)],
)
def test_parece_importe(texto, esperado):
    assert parece_importe(texto) is esperado


def test_normalizar_colapsa_el_padding_del_banco():
    assert normalizar("ADVANCE - FUNDING SOURCE - TWCF         0800065") == (
        "ADVANCE - FUNDING SOURCE - TWCF 0800065"
    )


def test_normalizar_quita_acentos():
    assert normalizar("Pago en una sola exhibición") == "PAGO EN UNA SOLA EXHIBICION"


def test_extraer_clabe():
    assert extraer_clabe("FCS003845101892 0000001 021180040573182974") == "021180040573182974"
    assert extraer_clabe("ADVANCE - FUNDING SOURCE - TWCF 0800065") is None


def test_extraer_rfc():
    assert extraer_rfc("PAGO DE FACTURA 10139 RFC DIZM6110081C4 IVA 0.00") == "DIZM6110081C4"
