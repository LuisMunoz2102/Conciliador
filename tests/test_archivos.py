import pytest

from conciliador.core.archivos import ruta_legible


def test_archivo_libre_se_usa_tal_cual(tmp_path):
    """Sin bloqueo no debe copiarse nada: se trabaja sobre el original."""
    original = tmp_path / "datos.xlsx"
    original.write_bytes(b"PK\x03\x04contenido")
    with ruta_legible(original) as p:
        assert p == original


def test_archivo_inexistente_lo_dice_claro(tmp_path):
    with pytest.raises(FileNotFoundError, match="no se encontró"):
        with ruta_legible(tmp_path / "no_existe.xlsx"):
            pass


def test_acepta_ruta_como_texto(tmp_path):
    original = tmp_path / "datos.xlsx"
    original.write_bytes(b"x")
    with ruta_legible(str(original)) as p:
        assert p.read_bytes() == b"x"
