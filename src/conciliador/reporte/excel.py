"""Reporte de conciliación en Excel.

La hoja de resumen abre con el cuadre: cada peso que entró al banco queda en
exactamente una categoría y la diferencia contra el total del banco debe ser cero.
Sin ese cuadre el resto de las hojas no son auditables.
"""

from __future__ import annotations

from pathlib import Path

import xlsxwriter

from ..core.dinero import a_decimal
from ..core.modelos import Estado
from ..motor.cascada import Resultado, ResultadoDeposito

_CATEGORIAS = {
    Estado.AUTO: "Conciliado",
    Estado.REVISAR: "Conciliado (revisar comisión)",
    Estado.AMBIGUO: "Ambiguo",
    Estado.FACTORAJE: "Factoraje por aplicar",
    Estado.RUIDO: "Ruido bancario",
    Estado.SIN_MATCH: "Sin identificar",
}


class _Formatos:
    def __init__(self, libro):
        self.titulo = libro.add_format({"bold": True, "font_size": 14})
        self.encabezado = libro.add_format(
            {"bold": True, "bg_color": "#1F3864", "font_color": "white", "border": 1,
             "text_wrap": True, "valign": "vcenter"}
        )
        self.dinero = libro.add_format({"num_format": "#,##0.00"})
        self.dinero_bold = libro.add_format({"num_format": "#,##0.00", "bold": True, "top": 1})
        self.fecha = libro.add_format({"num_format": "dd/mm/yyyy"})
        self.pct = libro.add_format({"num_format": "0.000%"})
        self.bold = libro.add_format({"bold": True})
        self.ok = libro.add_format({"bg_color": "#C6EFCE", "font_color": "#006100"})
        self.alerta = libro.add_format({"bg_color": "#FFC7CE", "font_color": "#9C0006"})
        self.aviso = libro.add_format({"bg_color": "#FFEB9C", "font_color": "#9C5700"})
        self.envoltura = libro.add_format({"text_wrap": True, "valign": "top"})


def _tabla(hoja, formatos: _Formatos, encabezados: list[tuple[str, int]], fila: int = 0) -> int:
    for col, (texto, ancho) in enumerate(encabezados):
        hoja.write(fila, col, texto, formatos.encabezado)
        hoja.set_column(col, col, ancho)
    hoja.freeze_panes(fila + 1, 0)
    return fila + 1


def _dias(resultado: Resultado, factura) -> int:
    return (resultado.estado_cuenta.periodo_fin - factura.fecha_emision).days


def _antiguedad(dias: int) -> str:
    if dias <= 30:
        return "0-30"
    if dias <= 60:
        return "31-60"
    if dias <= 90:
        return "61-90"
    return "más de 90"


def generar(resultado: Resultado, destino: str | Path) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    libro = xlsxwriter.Workbook(str(destino), {"default_date_format": "dd/mm/yyyy"})
    f = _Formatos(libro)

    _resumen(libro, f, resultado)
    _depositos(libro, f, resultado)
    _ya_cobradas(libro, f, resultado)
    _por_cobrar(libro, f, resultado)
    _revisar(libro, f, resultado)
    _log(libro, f, resultado)

    libro.close()
    return destino


def _resumen(libro, f: _Formatos, r: Resultado) -> None:
    hoja = libro.add_worksheet("00 Resumen")
    hoja.set_column(0, 0, 44)
    hoja.set_column(1, 1, 20)
    hoja.set_column(2, 2, 16)

    ec = r.estado_cuenta
    hoja.write(0, 0, "Conciliación de cobros", f.titulo)
    hoja.write(1, 0, "Cuenta")
    hoja.write(1, 1, ec.cuenta)
    hoja.write(2, 0, "Periodo del estado de cuenta")
    hoja.write(2, 1, f"{ec.periodo_inicio:%d/%m/%Y} al {ec.periodo_fin:%d/%m/%Y}")

    fila = 4
    hoja.write(fila, 0, "Cuadre de los depósitos", f.bold)
    fila += 1
    hoja.write(fila, 0, "Categoría", f.encabezado)
    hoja.write(fila, 1, "Importe", f.encabezado)
    hoja.write(fila, 2, "Depósitos", f.encabezado)
    fila += 1

    totales: dict[str, list[int]] = {}
    for d in r.depositos:
        clave = _CATEGORIAS[d.estado]
        acumulado = totales.setdefault(clave, [0, 0])
        acumulado[0] += d.movimiento.abono_cent
        acumulado[1] += 1

    suma = 0
    for clave, (importe, cuenta) in sorted(totales.items(), key=lambda kv: -kv[1][0]):
        hoja.write(fila, 0, clave)
        hoja.write_number(fila, 1, float(a_decimal(importe)), f.dinero)
        hoja.write_number(fila, 2, cuenta)
        suma += importe
        fila += 1

    hoja.write(fila, 0, "Suma de las categorías", f.bold)
    hoja.write_number(fila, 1, float(a_decimal(suma)), f.dinero_bold)
    fila += 1
    hoja.write(fila, 0, "Total de abonos declarado por el banco", f.bold)
    hoja.write_number(fila, 1, float(a_decimal(ec.total_abonos_cent_declarado)), f.dinero_bold)
    fila += 1
    diferencia = suma - ec.total_abonos_cent_declarado
    hoja.write(fila, 0, "Diferencia", f.bold)
    hoja.write_number(
        fila, 1, float(a_decimal(diferencia)), f.ok if diferencia == 0 else f.alerta
    )

    fila += 2
    nuevas = [c for c in r.conciliadas if not c.marcada_cobrada]
    hoja.write(fila, 0, "Hallazgos", f.bold)
    fila += 1
    for etiqueta, docs in (
        ("Facturas marcadas como pendientes que en realidad ya se cobraron", nuevas),
        ("Facturas que siguen por cobrar", r.por_cobrar),
    ):
        hoja.write(fila, 0, etiqueta)
        hoja.write_number(fila, 1, float(a_decimal(sum(d.total_cent for d in docs))), f.dinero)
        hoja.write_number(fila, 2, len(docs))
        fila += 1

    fila += 1
    hoja.write(
        fila, 0,
        "El periodo del estado de cuenta acota lo verificable: las facturas anteriores "
        "a él no pueden confirmarse con este archivo.",
        f.envoltura,
    )


def _depositos(libro, f: _Formatos, r: Resultado) -> None:
    hoja = libro.add_worksheet("01 Depósitos")
    fila = _tabla(hoja, f, [
        ("Fecha", 12), ("Importe", 16), ("Contraparte", 32), ("Situación", 24),
        ("Regla", 8), ("Confianza", 10), ("Facturas", 30), ("Explicación", 70),
        ("Referencia", 14), ("Concepto del banco", 46),
    ])
    for d in r.depositos:
        hoja.write_datetime(fila, 0, d.movimiento.fecha, f.fecha)
        hoja.write_number(fila, 1, float(a_decimal(d.movimiento.abono_cent)), f.dinero)
        hoja.write(fila, 2, d.contraparte.nombre)
        estilo = {
            Estado.AUTO: f.ok, Estado.REVISAR: f.ok,
            Estado.AMBIGUO: f.aviso, Estado.FACTORAJE: f.aviso,
            Estado.SIN_MATCH: f.alerta,
        }.get(d.estado)
        hoja.write(fila, 3, d.estado.value, estilo)
        hoja.write(fila, 4, d.regla.value)
        hoja.write_number(fila, 5, d.confianza)
        hoja.write(fila, 6, ", ".join(c.referencia for c in d.facturas))
        hoja.write(fila, 7, d.explicacion, f.envoltura)
        hoja.write(fila, 8, d.movimiento.referencia or "")
        hoja.write(fila, 9, d.movimiento.concepto)
        fila += 1
    hoja.autofilter(0, 0, max(fila - 1, 1), 9)


def _ya_cobradas(libro, f: _Formatos, r: Resultado) -> None:
    hoja = libro.add_worksheet("02 Ya cobradas")
    hoja.write(0, 0, "Facturas que tienes como pendientes pero que el banco ya pagó", f.titulo)
    fila = _tabla(hoja, f, [
        ("Factura", 24), ("Fecha emisión", 14), ("Cliente", 34), ("Importe factura", 16),
        ("Fecha del depósito", 16), ("Importe depositado", 18), ("Diferencia", 14),
        ("Cómo se identificó", 66),
    ], fila=2)

    for d in r.depositos:
        for c in d.facturas:
            if c.marcada_cobrada:
                continue
            hoja.write(fila, 0, c.referencia)
            hoja.write_datetime(fila, 1, c.fecha_emision, f.fecha)
            hoja.write(fila, 2, c.nombre_receptor)
            hoja.write_number(fila, 3, float(a_decimal(c.total_cent)), f.dinero)
            hoja.write_datetime(fila, 4, d.movimiento.fecha, f.fecha)
            hoja.write_number(fila, 5, float(a_decimal(d.movimiento.abono_cent)), f.dinero)
            hoja.write_number(fila, 6, float(a_decimal(d.diferencia_cent)), f.dinero)
            hoja.write(fila, 7, d.explicacion, f.envoltura)
            fila += 1
    hoja.autofilter(2, 0, max(fila - 1, 3), 7)


def _por_cobrar(libro, f: _Formatos, r: Resultado) -> None:
    hoja = libro.add_worksheet("03 Por cobrar")
    fila = _tabla(hoja, f, [
        ("Factura", 24), ("Fecha emisión", 14), ("Cliente", 34), ("Método", 10),
        ("Importe", 16), ("Días", 8), ("Antigüedad", 14),
    ])
    for c in sorted(r.por_cobrar, key=lambda x: (x.nombre_receptor, x.fecha_emision)):
        dias = _dias(r, c)
        hoja.write(fila, 0, c.referencia)
        hoja.write_datetime(fila, 1, c.fecha_emision, f.fecha)
        hoja.write(fila, 2, c.nombre_receptor)
        hoja.write(fila, 3, c.metodo_pago.value)
        hoja.write_number(fila, 4, float(a_decimal(c.total_cent)), f.dinero)
        hoja.write_number(fila, 5, dias)
        hoja.write(fila, 6, _antiguedad(dias), f.alerta if dias > 90 else None)
        fila += 1
    hoja.autofilter(0, 0, max(fila - 1, 1), 6)


def _revisar(libro, f: _Formatos, r: Resultado) -> None:
    hoja = libro.add_worksheet("04 Revisar")
    hoja.write(0, 0, "Depósitos con más de una explicación posible", f.titulo)
    hoja.write(
        1, 0,
        "El sistema no elige entre combinaciones equivalentes: hacerlo sería inventar el dato. "
        "Escribe tu decisión en la última columna.",
        f.envoltura,
    )
    fila = _tabla(hoja, f, [
        ("Fecha", 12), ("Importe", 16), ("Contraparte", 28), ("Opción", 8),
        ("Facturas de la combinación", 56), ("Importe bruto", 16), ("Comisión", 12),
        ("Decisión", 18),
    ], fila=3)

    for d in r.depositos:
        if d.estado is not Estado.AMBIGUO:
            continue
        for n, combo in enumerate(d.alternativas, start=1):
            bruto = sum(c.total_cent for c in combo)
            hoja.write_datetime(fila, 0, d.movimiento.fecha, f.fecha)
            hoja.write_number(fila, 1, float(a_decimal(d.movimiento.abono_cent)), f.dinero)
            hoja.write(fila, 2, d.contraparte.nombre)
            hoja.write_number(fila, 3, n)
            hoja.write(fila, 4, ", ".join(c.referencia for c in combo), f.envoltura)
            hoja.write_number(fila, 5, float(a_decimal(bruto)), f.dinero)
            if bruto:
                hoja.write_number(fila, 6, 1 - d.movimiento.abono_cent / bruto, f.pct)
            fila += 1
    hoja.autofilter(3, 0, max(fila - 1, 4), 7)


def _log(libro, f: _Formatos, r: Resultado) -> None:
    hoja = libro.add_worksheet("05 Validación")
    hoja.write(0, 0, "Comprobaciones del estado de cuenta contra los totales del banco", f.titulo)
    fila = _tabla(hoja, f, [
        ("Comprobación", 52), ("Declarado por el banco", 34), ("Obtenido del PDF", 44),
        ("Resultado", 14),
    ], fila=2)
    for v in r.estado_cuenta.validaciones:
        hoja.write(fila, 0, v.nombre)
        hoja.write(fila, 1, v.esperado)
        hoja.write(fila, 2, v.obtenido)
        if v.ok:
            hoja.write(fila, 3, "correcto", f.ok)
        else:
            hoja.write(fila, 3, "falla" if v.critica else "aviso", f.alerta if v.critica else f.aviso)
        fila += 1
