"""Modelo canónico.

Es deliberadamente simétrico: cobranza son los ABONOS del banco contra las facturas
EMITIDAS, y pagos a proveedores son los CARGOS contra las RECIBIDAS. Manteniendo la
dirección y el rol como datos (y no como dos jerarquías distintas), el segundo proyecto
del taller reutiliza este núcleo y el parser sin reescribirlos.
"""

from __future__ import annotations

import hashlib
from datetime import date, time
from enum import Enum

from pydantic import BaseModel, Field

from .dinero import formatear


class Direccion(str, Enum):
    ABONO = "ABONO"
    CARGO = "CARGO"


class RolFiscal(str, Enum):
    EMITIDA = "EMITIDA"
    RECIBIDA = "RECIBIDA"


class MetodoPago(str, Enum):
    PUE = "PUE"
    PPD = "PPD"
    DESCONOCIDO = "DESCONOCIDO"


class Regla(str, Enum):
    R0_COMPLEMENTO = "R0"
    R1_EXACTO = "R1"
    R2_SUBCONJUNTO = "R2"
    R4_FACTORAJE = "R4"
    R5_RUIDO = "R5"
    SIN_REGLA = "-"


class Estado(str, Enum):
    AUTO = "CONCILIADO"
    REVISAR = "REVISAR"
    AMBIGUO = "AMBIGUO"
    SIN_MATCH = "SIN IDENTIFICAR"
    RUIDO = "RUIDO BANCARIO"
    FACTORAJE = "FACTORAJE POR APLICAR"


class MovimientoBancario(BaseModel):
    cuenta: str
    fecha: date
    hora: time | None = None
    sucursal: str | None = None
    descripcion: str
    cargo_cent: int = 0
    abono_cent: int = 0
    saldo_cent: int = 0
    referencia: str | None = None
    concepto: str = ""
    clabe_ordenante: str | None = None
    pagina: int = 0
    orden: int = 0

    @property
    def direccion(self) -> Direccion:
        return Direccion.ABONO if self.abono_cent > 0 else Direccion.CARGO

    @property
    def importe_cent(self) -> int:
        return self.abono_cent if self.abono_cent > 0 else self.cargo_cent

    @property
    def id(self) -> str:
        crudo = f"{self.cuenta}|{self.fecha}|{self.cargo_cent}|{self.abono_cent}|{self.saldo_cent}|{self.referencia}|{self.concepto}"
        return hashlib.sha1(crudo.encode("utf-8")).hexdigest()[:12]

    def __str__(self) -> str:
        return f"{self.fecha:%d/%m/%Y} {formatear(self.importe_cent):>16} {self.concepto[:50]}"


class Validacion(BaseModel):
    nombre: str
    esperado: str
    obtenido: str
    ok: bool
    critica: bool = True


class EstadoCuenta(BaseModel):
    cuenta: str
    periodo_inicio: date
    periodo_fin: date
    saldo_inicial_cent: int
    saldo_final_cent: int
    total_movimientos_declarado: int
    total_abonos_cent_declarado: int
    total_cargos_cent_declarado: int
    numero_abonos_declarado: int | None = None
    numero_cargos_declarado: int | None = None
    movimientos: list[MovimientoBancario] = Field(default_factory=list)
    validaciones: list[Validacion] = Field(default_factory=list)

    @property
    def abonos(self) -> list[MovimientoBancario]:
        return [m for m in self.movimientos if m.abono_cent > 0]

    @property
    def cargos(self) -> list[MovimientoBancario]:
        return [m for m in self.movimientos if m.cargo_cent > 0]

    @property
    def valido(self) -> bool:
        return all(v.ok for v in self.validaciones if v.critica)


class Comprobante(BaseModel):
    uuid: str
    rol: RolFiscal
    tipo: str = "Factura"
    serie: str | None = None
    folio: str | None = None
    fecha_emision: date
    rfc_emisor: str
    nombre_emisor: str = ""
    rfc_receptor: str
    nombre_receptor: str = ""
    subtotal_cent: int = 0
    iva_cent: int = 0
    ret_iva_cent: int = 0
    ret_isr_cent: int = 0
    total_cent: int = 0
    moneda: str = "MXN"
    metodo_pago: MetodoPago = MetodoPago.DESCONOCIDO
    forma_pago: str | None = None
    estado_sat: str = "Vigente"

    monto_cobrable_cent: int = 0
    saldo_pendiente_cent: int = 0
    marcada_cobrada: bool = False
    fila_origen: int = 0

    @property
    def es_nota_credito(self) -> bool:
        return "NOTA" in self.tipo.upper() or self.total_cent < 0

    @property
    def contraparte_rfc(self) -> str:
        """Quien debe pagar si la factura es emitida; a quien se le paga si es recibida."""
        return self.rfc_receptor if self.rol is RolFiscal.EMITIDA else self.rfc_emisor

    @property
    def contraparte_nombre(self) -> str:
        return self.nombre_receptor if self.rol is RolFiscal.EMITIDA else self.nombre_emisor

    @property
    def vigente(self) -> bool:
        return self.estado_sat.strip().lower().startswith("vigente")

    @property
    def referencia(self) -> str:
        return f"{self.serie or ''}{self.folio or ''}".strip() or self.uuid[:8]


class ComplementoPago(BaseModel):
    uuid: str
    fecha_pago: date
    monto_cent: int
    uuid_relacionado: str
    forma_pago: str | None = None
    moneda: str = "MXN"
    num_operacion: str | None = None
    cuenta_origen: str | None = None
    cuenta_destino: str | None = None


class Asignacion(BaseModel):
    movimiento_id: str
    comprobante_uuid: str | None = None
    importe_aplicado_cent: int = 0
    regla: Regla = Regla.SIN_REGLA
    confianza: int = 0
    estado: Estado = Estado.SIN_MATCH
    diferencia_cent: int = 0
    contraparte: str = ""
    explicacion: str = ""
