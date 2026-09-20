"""Interfaz de línea de comandos."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .core.dinero import formatear
from .core.modelos import Estado
from .ingesta.facturas_excel import leer_facturas
from .ingesta.santander_pdf import leer_estado_cuenta
from .ingesta.validacion import exigir_validez, validar
from .motor.cascada import conciliar
from .reglas.esquema import TipoContraparte, cargar_reglas, resolver
from .reporte.excel import generar

app = typer.Typer(add_completion=False, help="Conciliación de cobros contra el banco.")
consola = Console()

RAIZ = Path(__file__).resolve().parents[2]
DATOS = RAIZ / "datos"
SALIDA = RAIZ / "salida"
REGLAS = RAIZ / "config" / "clientes.yaml"


def _mas_reciente(carpeta: Path, patron: str, que: str) -> Path:
    archivos = [a for a in carpeta.glob(patron) if not a.name.startswith("~$")]
    if not archivos:
        raise typer.BadParameter(
            f"No encontré {que} en {carpeta}. Copia el archivo ahí o indícalo con la opción."
        )
    return max(archivos, key=lambda a: a.stat().st_mtime)


@app.command("conciliar")
def conciliar_cobros(
    banco: Path = typer.Option(None, "--banco", help="PDF del estado de cuenta Santander."),
    facturas: Path = typer.Option(None, "--facturas", help="Excel con las facturas emitidas."),
    salida: Path = typer.Option(None, "--salida", help="Excel del reporte a generar."),
    reglas: Path = typer.Option(None, "--reglas", help="YAML de contrapartes."),
    hoja: str = typer.Option(None, "--hoja", help="Hoja del Excel de facturas."),
) -> None:
    """Cruza los depósitos del banco contra las facturas y genera el reporte."""
    banco = banco or _mas_reciente(DATOS, "*.pdf", "el estado de cuenta en PDF")
    facturas = facturas or _mas_reciente(DATOS, "*.xlsx", "el Excel de facturas")

    consola.print(f"Estado de cuenta : [cyan]{banco.name}[/]")
    consola.print(f"Facturas         : [cyan]{facturas.name}[/]")

    estado = leer_estado_cuenta(banco)
    validar(estado)
    for v in estado.validaciones:
        if not v.ok and not v.critica:
            consola.print(f"[yellow]Aviso[/] {v.nombre}: banco {v.esperado}, movimientos {v.obtenido}")
    try:
        exigir_validez(estado)
    except Exception as exc:
        consola.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc

    consola.print(
        f"Periodo          : [cyan]{estado.periodo_inicio:%d/%m/%Y} al {estado.periodo_fin:%d/%m/%Y}[/]"
        f"  ({len(estado.movimientos)} movimientos, {len(estado.abonos)} abonos)"
    )

    catalogo = leer_facturas(facturas, hoja)
    resultado = conciliar(estado, catalogo, cargar_reglas(reglas or REGLAS))

    tabla = Table(title="Depósitos", show_lines=False)
    tabla.add_column("Fecha")
    tabla.add_column("Importe", justify="right")
    tabla.add_column("Contraparte")
    tabla.add_column("Situación")
    tabla.add_column("Facturas")
    colores = {
        Estado.AUTO: "green", Estado.REVISAR: "green", Estado.AMBIGUO: "yellow",
        Estado.FACTORAJE: "yellow", Estado.RUIDO: "dim", Estado.SIN_MATCH: "red",
    }
    for d in resultado.depositos:
        color = colores[d.estado]
        tabla.add_row(
            f"{d.movimiento.fecha:%d/%m/%Y}",
            formatear(d.movimiento.abono_cent),
            d.contraparte.nombre[:30],
            f"[{color}]{d.estado.value}[/]",
            ", ".join(c.referencia for c in d.facturas)[:34],
        )
    consola.print(tabla)

    nuevas = [c for c in resultado.conciliadas if not c.marcada_cobrada]
    consola.print(
        f"\n[bold green]{len(nuevas)} facturas que tenías como pendientes ya están cobradas[/]"
        f"  ({formatear(sum(c.total_cent for c in nuevas))})"
    )
    consola.print(
        f"[bold]{len(resultado.por_cobrar)} facturas siguen por cobrar[/]"
        f"  ({formatear(sum(c.total_cent for c in resultado.por_cobrar))})"
    )

    destino = salida or SALIDA / (
        f"conciliacion_{estado.periodo_inicio:%Y_%m}_al_{estado.periodo_fin:%d}.xlsx"
    )
    generar(resultado, destino)
    consola.print(f"\nReporte generado: [cyan]{destino}[/]")


@app.command("sugerir-reglas")
def sugerir_reglas(
    banco: Path = typer.Option(None, "--banco", help="PDF del estado de cuenta."),
    reglas: Path = typer.Option(None, "--reglas", help="YAML de contrapartes."),
) -> None:
    """Lista los depósitos cuyo origen no está mapeado y propone el bloque YAML."""
    banco = banco or _mas_reciente(DATOS, "*.pdf", "el estado de cuenta en PDF")
    estado = leer_estado_cuenta(banco)
    catalogo = cargar_reglas(reglas or REGLAS)

    sin_mapear = [
        m for m in estado.abonos
        if resolver(m, catalogo).tipo is TipoContraparte.DESCONOCIDA
    ]
    if not sin_mapear:
        consola.print("[green]Todos los depósitos del periodo tienen contraparte identificada.[/]")
        return

    consola.print(f"[yellow]{len(sin_mapear)} depósitos sin identificar:[/]\n")
    for concepto, veces in Counter(m.concepto for m in sin_mapear).most_common():
        importe = sum(m.abono_cent for m in sin_mapear if m.concepto == concepto)
        clabe = next((m.clabe_ordenante for m in sin_mapear if m.concepto == concepto), None)
        consola.print(f"  {formatear(importe):>16}  x{veces}  {concepto}")
        consola.print("[dim]    - rfc: PENDIENTE")
        consola.print(f"[dim]      nombre: \"{concepto[:40]}\"")
        if clabe:
            consola.print(f"[dim]      clabe_ordenante: [\"{clabe}\"]")
        consola.print(f"[dim]      patrones: [\"{concepto.split()[0]}\"]\n")


if __name__ == "__main__":
    app()
