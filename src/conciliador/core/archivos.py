"""Lectura de insumos que pueden estar abiertos en otra aplicación.

Excel bloquea en exclusiva los archivos que tiene abiertos, sobre todo si están en
OneDrive con autoguardado, y entonces `open()` falla con PermissionError. Tener el
Excel abierto mientras se revisa la conciliación es lo normal, no la excepción, así
que en lugar de exigir que se cierre se trabaja sobre una copia temporal.

`shutil.copy2` sí puede copiarlo porque en Windows usa `CopyFile2`, que respeta el
modo de uso compartido con el que Excel abrió el archivo.
"""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class ArchivoBloqueado(RuntimeError):
    pass


def _legible(ruta: Path) -> bool:
    try:
        with ruta.open("rb"):
            return True
    except PermissionError:
        return False


@contextmanager
def ruta_legible(ruta: str | Path) -> Iterator[Path]:
    """Entrega una ruta que se puede abrir, copiando el archivo si está bloqueado."""
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"no se encontró el archivo: {ruta}")
    if _legible(ruta):
        yield ruta
        return

    # La limpieza es tolerante: si el lector todavía sostiene el archivo, borrar la
    # carpeta temporal puede fallar, y eso no debe tumbar una conciliación ya terminada.
    with tempfile.TemporaryDirectory(prefix="conciliador_", ignore_cleanup_errors=True) as carpeta:
        copia = Path(carpeta) / ruta.name
        try:
            shutil.copy2(ruta, copia)
        except OSError as exc:
            raise ArchivoBloqueado(
                f"No se pudo leer «{ruta.name}» porque otra aplicación lo tiene bloqueado, "
                "y tampoco se pudo copiar. Ciérralo en Excel y vuelve a intentar."
            ) from exc
        yield copia
