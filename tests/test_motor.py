from conciliador.core.dinero import a_centavos
from conciliador.motor.subconjunto import buscar, interseccion, rango_por_comision


def test_encuentra_la_combinacion_unica():
    montos = [1000, 2500, 400, 7000]
    r = buscar(montos, 3500, 3500)
    assert r.unica
    assert sorted(r.soluciones[0]) == [0, 1]


def test_no_inventa_cuando_no_hay_solucion():
    r = buscar([1000, 2000], 5500, 5500)
    assert not r.soluciones
    assert not r.unica


def test_varias_combinaciones_se_reportan_como_ambiguas():
    """Con tarifas de flete repetidas, varias sumas dan lo mismo."""
    montos = [500, 500, 1000, 1500]
    r = buscar(montos, 2000, 2000)
    assert r.ambigua
    assert not r.unica


def test_la_interseccion_revela_lo_que_si_es_seguro():
    """Aunque la combinación exacta sea ambigua, lo común a todas es certeza."""
    # 8000 solo se alcanza incluyendo el monto grande, acompañado de uno de los chicos.
    montos = [7800, 100, 200, 150, 50]
    r = buscar(montos, 8000, 8000)
    assert r.ambigua
    comun = interseccion(r.soluciones)
    assert 0 in comun  # el de 7800 está en todas


def test_interseccion_vacia_cuando_no_hay_nada_comun():
    assert interseccion([(0, 1), (2, 3)]) == set()


def test_interseccion_sin_soluciones():
    assert interseccion([]) == set()


def test_rango_por_comision_cubre_el_bruto_esperado():
    """127,312.62 salió de una factura de 128,783.20 con 1.142% de comisión."""
    minimo, maximo = rango_por_comision(a_centavos("127,312.62"), 0.005, 0.025)
    assert minimo <= a_centavos("128,783.20") <= maximo


def test_la_busqueda_respeta_el_limite_de_cardinalidad():
    montos = [1] * 10
    r = buscar(montos, 8, 8, max_cardinalidad=3)
    assert not r.soluciones
