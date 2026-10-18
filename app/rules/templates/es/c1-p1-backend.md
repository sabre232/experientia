---
id: c1-p1-backend
name: Ingeniería de API backend
category: c1
priority: p1
layer: structure
trigger_default: always
tags: engineering; architecture
keywords: API; backend; interfaz
description: contrato primero + semántica de error + idempotencia y límites
source: built-in
from: eng-backend
---

Desarrollo backend/API — reglas:

Contrato:
- Definir el esquema entrada/salida de la API antes de escribir la implementación; cambiar un contrato significa cambiar primero la doc/los tests, y luego el código.
- La nomenclatura de los campos expuestos debe mantenerse coherente con la API existente; NUNCA varias grafías para el mismo significado.

Errores y estados:
- Usar los códigos HTTP correctos (4xx error de cliente, 5xx error de servidor); el cuerpo de error lleva un code legible por máquina + un message legible por humano.
- NUNCA tragar una excepción y devolver un 200 vacío; o tratar, o propagar.

Idempotencia y límites:
- Las escrituras (sobre todo las que tocan dinero) necesitan una clave de idempotencia; NUNCA suponer que una petición llega solo una vez.
- Validar siempre los parámetros de entrada (tipo/rango/longitud); NUNCA confiar en el llamador.

Registro:
- Anotar « qué pasó + contexto clave »; NUNCA registrar secrets, tokens, campos sensibles del cuerpo de petición.
