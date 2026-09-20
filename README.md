# Conciliador

Conciliación de cobros para BDB LOGISTICA SA DE CV: cruza las **facturas emitidas** (CFDI) contra
los **depósitos** que entran a la cuenta de cheques Santander, y produce un reporte de Excel
auditable.

## Insumos

| Insumo | Origen | Formato |
|---|---|---|
| Estado de cuenta | Santander Enlace → "Consulta de Movimientos" → imprimir a PDF | `.pdf` |
| Facturas emitidas | MiAdminXML → `RFC_Emitidas_AAAA_MM_Facturas.xlsx` | `.xlsx` |
| Complementos de pago | MiAdminXML → `RFC_Emitidas_AAAA_MM_Pagos.xlsx` | `.xlsx` |

Los tres archivos contienen información fiscal y bancaria real, por lo que `datos/` y `salida/`
están excluidos del repositorio.

## Uso

```
conciliador conciliar --banco datos/estado_cuenta.pdf \
                      --facturas datos/BLO221014NK0_Emitidas_2026_06_Facturas.xlsx \
                      --pagos datos/BLO221014NK0_Emitidas_2026_06_Pagos.xlsx \
                      --salida salida/conciliacion_2026_06.xlsx
```

Para descubrir depósitos cuyo origen todavía no está mapeado en `config/clientes.yaml`:

```
conciliador sugerir-reglas --banco datos/estado_cuenta.pdf
```

## Cómo decide el motor

Las reglas corren en cascada, de mayor a menor confianza, y cada factura asignada sale del pool:

| Regla | Qué hace |
|---|---|
| `R5` | Aparta el ruido bancario (intereses, traspasos internos) |
| `R0` | Usa el complemento de pago como evidencia fiscal directa (`UUIDRel` + monto + fecha) |
| `R4` | Aparta los depósitos de factoraje antes de que el motor intente casarlos |
| `R1` | Cruce exacto 1:1 por monto, cliente y ventana de fechas |
| `R2` | Un depósito que liquida varias facturas, solo con pocas candidatas y solución única |

Dos principios que no se negocian:

- **Nada se descarta, todo se clasifica.** Cada peso que entró al banco queda en exactamente una
  categoría, de modo que `Conciliado + Factoraje + Ruido + Sin identificar = Total de abonos`.
- **Si hay más de una combinación posible, no se concilia.** Se marca `AMBIGUO` y decide una
  persona. Elegir una combinación al azar sería fabricar información contable.

## Configuración

`config/clientes.yaml` traduce el concepto bancario a una contraparte. Se edita sin tocar código.
La resolución intenta primero la **CLABE ordenante** (determinista) y después los patrones de texto.
No hay coincidencia difusa de razones sociales: con nombres mexicanos produce falsos positivos.

## Desarrollo

```
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```
