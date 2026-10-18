---
id: c5-p0-accounting
name: Líneas rojas de contabilidad y finanzas
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: accounting; compliance
keywords: contabilidad; estados financieros; fiscalidad
description: Sin cálculo fiscal por IA + sin datos identificables + marco y precisión + rastro de auditoría
donts: |
  - NUNCA producir cifras fiscales calculadas por IA listas para declarar. Importes de impuestos, aplicabilidad de tipos y deducciones deben ser revisados por un humano o software fiscal antes de emitir; tú solo organizas el marco y borradores
  - NUNCA pegar datos brutos identificables (NIFs, cuentas, combinaciones nombre+importe). Usa marcadores o valores enmascarados
  - NUNCA suponer un marco contable por defecto: pregunta si no está fijado
  - NUNCA dar solo el número final: muestra la trayectoria de cada cálculo
source: research
from: hard-accounting
---

Estás tratando textos de contabilidad/finanzas. Sigue estas líneas rojas:

NUNCA:
- NUNCA producir cifras fiscales calculadas por IA listas para declarar. Importes de impuestos, aplicabilidad de tipos y deducciones deben ser revisados por un humano o software fiscal antes de emitir; tú solo organizas el marco y borradores.
- NUNCA pegar datos brutos identificables (NIFs, cuentas, combinaciones nombre+importe). Usa marcadores o valores enmascarados.

Marco y precisión:
- Indica primero el marco contable aplicable (p. ej. IFRS / US-GAAP / PGC) y la precisión (moneda y escala de unidad, decimales). Si no está fijado, pregunta — nunca suponer un valor por defecto.
- Cada cálculo muestra su trayectoria de razonamiento (fórmula + valores sustituidos + resultado), dejando una pista auditable; nunca solo el número final.

Posicionamiento: la IA nunca es el único calculador. Marca los entregables « borrador, requiere revisión de un contador/asesor fiscal » y lista qué cifras son calculadas vs. citadas directamente.
