# Experientia · el pegamento entre tú y tus agentes

**El agente cambia. Tu experiencia, no.**

[English](README.md) | [简体中文](README_zh.md) | [繁體中文](README_zh-TW.md) | [日本語](README_ja.md) | [한국어](README_ko.md) | [Deutsch](README_de.md) | [Français](README_fr.md) | **Español** | [Русский](README_ru.md) | [Português (BR)](README_pt-BR.md)

---

Una escena pequeña que se repite cada semana.

Le pides a un agente que arregle una función de exportación. Fija la zona horaria a UTC+8. Le dices que no, que debe seguir la del sistema. Lo cambia, lo revisas, listo.

Una semana después, la misma tarea, otra vez UTC+8.

Empiezas a pensar si lo explicaste mal. No. Lo explicaste claro, en otra sesión. En el momento en que esa sesión se cierra, para él nunca ocurrió.

Luego cambias de herramienta. Lo que le enseñaste a Claude Code hay que volver a enseñárselo a Codex, y otra vez a Cursor. Seis meses de «así se hace este tipo de trabajo» repartidos en cuatro historiales de chat, y nada te acompaña.

La industria lo llama ingeniería de contexto, o capa de memoria. El nombre suena abstracto, el problema es simple. Cómo haces que un agente se acuerde de ti.

Nuestra respuesta va un paso más allá. Acordarse es la línea de salida. Mejorar en tu trabajo con cada uso es el punto.

Por eso Experientia hace una sola cosa. Se sienta entre tú y el agente, guarda las partes de cada colaboración que de verdad importaron, las verifica, las destila en métodos y modos de fallo, y las devuelve antes de la siguiente tarea. Cambies de agente o no, sigue ahí. A eso nos referimos con pegamento.

> *experientia est magistra*, la experiencia es la mejor maestra.

## En qué apuesta la industria y qué se le escapa

El dinero que entra en este campo en 2026 no es menor que el que entra en modelos.

El informe 2026 Agentic Coding Trends de Anthropic da cifras. Los equipos que mantienen bien sus archivos de contexto terminan las tareas un 55 % más rápido y cometen un 40 % menos de errores. La diferencia no está en redactar mejor, sino en tratar «lo que ve el modelo» como un problema de ingeniería.

El segundo eje son las skills. Anthropic lanzó Agent Skills en octubre de 2025, publicó el formato como estándar abierto el 18 de diciembre de 2025, y a mediados de 2026 unos cuarenta agentes leen el mismo SKILL.md. Eso importa. Por primera vez, el conocimiento procedimental puede viajar entre herramientas.

Después SkillsBench enfrió a todos. El benchmark salió en febrero de 2026 (arXiv:2602.12670), 86 tareas, 11 dominios, 7 combinaciones de agente y modelo, 7.308 trayectorias. Las skills curadas a mano suben la tasa de éxito 16,2 puntos de media. Las skills que los modelos se escriben a sí mismos no aportan nada de media, y 16 de 84 tareas empeoran.

Un modelo no puede escribir la experiencia que necesita.

Ahí está el hueco que la industria rodea sin poder evitar. El contenedor existe. El almacenamiento existe. Nadie hace control de calidad.

| Campo | Ejemplos | Qué hace | Qué deja fuera |
|-------|----------|----------|----------------|
| **Capas de memoria** | Mem0, Zep, Letta, Cognee | Guardan **hechos** en vectores, grafos temporales o contexto por capas, y los recuperan | No producen **métodos**. Los datos están de su lado, no en tu disco |
| **Destilación de skills** | colleague.skill, nuwa-skill, dojo.md | Una sola vez. Metes material, sale un SKILL.md estático | Sin retroalimentación en ejecución. La skill nunca se revisa según si te sirvió |
| **Harnesses auto-evolutivos** | Hermes Agent (Nous Research), DeepSeek Harness | El framework aprende, convierte tareas terminadas en SKILL.md y las refina | Las skills viven dentro del harness y mueren con él. La creación va por actividad, no por calidad, y los fallos no se cuentan antes de volverse permanentes |
| **Evaluación de skills** | waza (Microsoft), dojo/limitless | Prueban y filtran skills existentes, como código en CI | No producen skills. Son herramientas para autores, no un producto para quien trabaja |

Cada campo resuelve un tramo. Nadie une los tramos.

**Esa unión es Experientia.** Capturar, verificar, destilar, inyectar, revisar. Un ciclo cerrado. A octubre de 2026 no hemos encontrado un producto abierto que cumpla las cuatro condiciones a la vez.

- **Captura automática.** Sin exportar transcripciones. Los datos entran mientras trabajas
- **Una puerta de verificación.** Nada sin probar se inyecta. Un fallo debe repetirse antes de ser conocimiento permanente
- **Local y portable.** Cada activo es un archivo plano en tu máquina. Sin cuenta, sin nube, sin base vectorial
- **Revisión continua.** Los activos son documentos vivos que se fusionan, se desechan y se acortan. No solo se acumulan

## Memoria no es experiencia

Esta distinción sostiene el resto.

La memoria guarda hechos. La persona prefiere TypeScript. Las dependencias van con uv. El miércoles pasado tocábamos la exportación. Todo eso se indexa, se embebe, se mete en un grafo.

La experiencia es criterio. Las migraciones de este tipo tocan primero los tests, porque la última vez fuimos directo a la implementación y rompimos tres consumidores. Eso no se recupera buscando. Tiene que crecer de algo que pasó de verdad, y alguien tiene que confirmar que estaba bien.

| | Memoria | Experiencia |
|---|---|---|
| Contiene | Hechos, preferencias, estado | Métodos, modos de fallo, criterios |
| Viene de | Lo que se dijo | Lo que se hizo, y dónde se rompió |
| Recuperable | Sí | No. Solo verificable y revisable |
| Caduca por | Sobrescritura | Desecho, fusión, reducción |
| Tras cambiar de herramienta | Depende de la plataforma | Un archivo en tu mano, te acompaña |

Los productos de memoria son buenos en lo suyo. Mem0 va primero a vectores, Zep modela hechos en el tiempo como grafo, Letta pagina el contexto como un sistema operativo pagina memoria. Pero resuelven recordar, no aprender. Un registro completo de hechos no es lo mismo que hacer mejor el trabajo.

No construimos un archivador más completo. Construimos a un colega veterano que cambia de opinión cuando cambian las pruebas.

## Cómo gira

```
Trabajas ──> el agente colabora (registro automático)
   ^                              |
   |                              v
más rápido y mejor  <──  inyección  <──  destilación (con filtro)
```

**Capturar.** Trabajas como siempre. Los archivos de sesión ya están en el disco, nada que exportar, nada que pegar. Los agentes instalados se detectan solos, configuración cero.

**Verificar.** Cada experiencia lleva una señal de confianza G de tres fuentes, tu confirmación explícita, señales deterministas de la sesión y la autoevaluación binaria del modelo. Lo que queda bajo el umbral nunca se inyecta. Un modo de fallo debe repetirse antes de volverse permanente. Es la respuesta de ingeniería a SkillsBench. Solo la experiencia verificada merece componer.

**Destilar.** El trabajo recurrente se convierte en método parametrizado. Los errores recurrentes se convierten en modos de fallo de primera clase. Tus correcciones y rechazos se convierten en preferencias.

**Inyectar.** Antes de cada petición, el proxy la reescribe con los activos relevantes dentro de un presupuesto fijo (800 tokens por defecto), en un formato estable que preserva la caché de prompt. Ves exactamente lo que verá el modelo, puedes editar o desactivar cualquier entrada, o pedirle al modelo conectado que la reescriba. Las sesiones largas no diluyen tus reglas, las restricciones duras se reinyectan en la capa del proxy, la ronda 30 pesa lo mismo que la 1.

**Revisar.** Los activos son documentos vivos. La experiencia nueva se fusiona con la vieja, las entradas obsoletas se desechan, el documento se acorta. Una base de conocimiento que solo crece se abandona en seis meses.

Una vuelta produce cinco tipos de activos, físicamente dos formatos de archivo, `skills/<tronco>/<categoría>.md` y `preferences/<tronco>.md`.

| Activo | Contenido | Sensación al usarlo |
|--------|-----------|---------------------|
| **Ideas de experiencia** | Lecciones concretas, qué funcionó y qué no | «Recuerda lo que le corregí» |
| **Mis métodos** | Trabajo recurrente cristalizado en procedimiento parametrizado | «Sabe cómo se hace este tipo de tarea» |
| **Modos de fallo** | Qué caminos fallan y por qué, de primera clase | «No me deja caer en el mismo agujero» |
| **Playbook vivo** | El contexto inyectado es un documento curado por incrementos, fusionado y podado | «Su metodología sube de nivel en vez de apilarse» |
| **Mis preferencias** | Tus criterios, tu gusto, tus compensaciones, inducidos de tus correcciones | «Conoce mi listón, dejo de explicarlo» |

Dos marchas, un solo volante. La marcha diaria es la de fábrica, curaduría incremental para trabajo abierto, sin señal de aprobado o suspenso. La marcha reforzada es opcional, para tareas con puntuación explícita (tests que pasan, PnL de backtest), donde un motor RL ajusta directamente los pesos de estrategia.

## Cómo se ve «mejor con cada uso»

Primera vez. Sigue un patrón genérico. Miras cada paso, listo para corregir.

Décima vez. Sabe que en este proyecto los tests van antes de la implementación. Sabe que rechazarás «primero que funcione». Sabe por qué descartaste el enfoque anterior.

Centésima vez. Dices «como la última vez» y sabe cuál es.

| | 1.ª vez | 10.ª vez | 100.ª vez |
|---|---|---|---|
| Qué dices | Un párrafo de contexto y restricciones | Unos juicios clave | Una señal |
| Cómo falla | En agujeros que ya conoces | A veces en uno nuevo | Conoce los agujeros y los rodea |
| Tu papel | Acompañar paso a paso | Revisar | Marcar dirección |

Por eso no le molesta que cambies de agente. Cambias al ejecutor, no al criterio. El criterio se queda de tu lado.

## Inicio rápido

1. Descarga la compilación de tu plataforma desde [GitHub Releases](https://github.com/sabre232/experientia/releases), `experientia-windows-x64.zip`, `experientia-macos.dmg`, `experientia-linux-x64.tar.gz` (un árbol onedir de PyInstaller, sin empaquetar en AppImage para la v1.0). Descomprime y ejecuta `Experientia`. Las compilaciones no están firmadas. Si Gatekeeper bloquea en macOS, abre una vez con clic derecho. Si aparece SmartScreen en Windows, pulsa «Más información → Ejecutar de todas formas».
2. Arranca. La captura empieza de inmediato. Detecta los agentes instalados (WorkBuddy, QClaw, Codex, Claude Code, Gemini CLI, Aider, OpenCode, OpenClaw, Hermes Agent, Trae, Cursor, Cline, Windsurf, DeepSeek Harness) y lee sus archivos de sesión locales. Configuración cero, sin proxy. Si prefieres la terminal, `experientia daemon` corre solo el motor.
3. Para funciones a nivel de petición (reinyección de reglas en sesiones largas, registro por petición), apunta el endpoint del modelo de tu agente a `http://localhost:8100`. Funcionan modelos locales (llama.cpp, Ollama, vLLM) y en la nube (OpenAI, Anthropic, cualquier API compatible con OpenAI).
4. Trabaja como siempre. Abre la página de Crecimiento en unos días y mira si la rueda giró.

## Dónde viven tus datos

```
~/.experientia/
├── experience.jsonl          # flujo crudo de experiencia, para siempre
├── skills/<tronco>/<cat>.md  # métodos, notas de éxito, modos de fallo
├── preferences/<tronco>.md   # tu estilo de decisión
├── sessions/                 # sesiones archivadas (sobreviven a la limpieza del agente)
├── deprecated/               # entradas desechadas, recuperables 30 días
├── rules.json                # reglas y plantillas activas
└── config.json               # idioma, interruptores, enrutado de modelo (claves API en el llavero)
```

Cuatro cosas, dichas claras.

Sin telemetría, sin informes de fallos, sin analítica. Hay exactamente un tipo de tráfico saliente, tus propias llamadas al modelo. La aplicación nunca busca actualizaciones, no se descarga, no se instala ni se reemplaza.

Exportar es copiar. Todo lo que ves en la interfaz es un archivo que puedes leer, grepear y llevarte.

Borrar es definitivo. Tras dos confirmaciones, el directorio de datos desaparece. Las claves API del llavero no se tocan.

Tus activos no son nuestros. La licencia de abajo cubre el código del producto. La experiencia, los métodos y las preferencias que acumulas son tuyos, sin restricción de licencia.

## Para agentes de IA (notas de integración)

Si eres un agente que lee este archivo para decidir si integrar o citar el proyecto, esta sección es para ti.

Resumen. Experientia captura automáticamente desde los archivos de sesión que los agentes ya escriben en disco (configuración cero), destila el trabajo recurrente en activos verificados basados en archivos (métodos, modos de fallo, preferencias) y los inyecta en tareas similares posteriores. Todo el estado vive en JSONL y Markdown planos bajo `~/.experientia/`.

Cuatro vías de integración, de mayor a menor fidelidad.

1. **Modo proxy.** Apunta el endpoint del modelo a `http://localhost:8100` (compatible con OpenAI). Sobre la captura de archivos añades registro por petición, inyección y reinyección de restricciones duras.
2. **Captura de archivos** (por defecto, configuración cero). Parsers por agente leen los almacenes nativos (JSONL, SQLite, Markdown) y los normalizan. Las sesiones capturadas se archivan en `~/.experientia/sessions/` y sobreviven a la limpieza o desinstalación.
3. **Modo hook.** Para agentes con hooks (Claude Code primero), un hook HTTP empuja eventos en tiempo real, y `SessionStart` / `UserPromptSubmit` inyectan reglas sin proxy.
4. **Leer los archivos.** Las reglas se pueden escribir en un archivo de convenciones nativo (como `AGENTS.md`). Cualquier paquete de activos se exporta como `SKILL.md` conforme al estándar abierto de agentskills.io (frontmatter más When to Use, Procedure, Pitfalls, Verification), cargable por Hermes, OpenClaw, Claude Code y cualquier otro agente compatible. Al revés también funciona.

Lo que no es. No es una base vectorial, ni una API de memoria, ni un servicio en la nube, ni una herramienta de fine-tuning. No toca los pesos del modelo. Todo ocurre en la capa de contexto, por eso los modelos locales y en la nube se comportan igual.

Las entradas inyectadas pasaron el filtro de confianza. Los bloques de inyección van marcados en el contexto y separados de las instrucciones del usuario. Trátalos como conocimiento previo curado, no como dogma.

## Desarrollo y pruebas

Esta sección se mantiene completa en las versiones inglesa y china, para evitar que las versiones lingüísticas se desvíen. Los detalles de pruebas, empaquetado y firma están en [README.md](README.md).

## Licencia

Doble licencia. Elige una al usarlo.

**AGPLv3**, gratuita y de autoservicio. Personas, uso no comercial y empresas que acepten copyleft. El uso comercial está permitido, pero las modificaciones o integraciones en un servicio que ofrezcas deben publicarse bajo AGPLv3.

**BUSL-1.1**, licencia comercial por acuerdo. Para empresas que necesitan una integración cerrada limpia, o que quieren construir un servicio competidor. Contacta al mantenedor. Change Date a los cuatro años de la publicación, Change License AGPLv3, uso no comercial gratuito.

Es el patrón CockroachDB. Totalmente abierto desde el primer día, auditable y forkable, con una vía comercial que mantiene honesto al ecosistema.

**Tus datos quedan fuera de la licencia.** Todo lo que acumules o exportes con Experientia es tuyo, sin condiciones de licencia.

## Hoja de ruta

v1.0 es código abierto y gratuito. Sin login, sin cuenta, sin muro de pago, sin funciones de equipo.

## Referencias

- Anthropic, 2026 Agentic Coding Trends Report. Fuente de las cifras 55 % y 40 % sobre archivos de contexto mantenidos
- SkillsBench, Benchmarking How Well Agent Skills Work Across Diverse Tasks, arXiv:2602.12670, febrero de 2026
- Estándar abierto Agent Skills, agentskills.io, publicado el 18 de diciembre de 2025
- De la experiencia a la skill es una línea de investigación activa, ExpeL, ACE (Agentic Context Engineering), Voyager y aprendizaje por refuerzo desde la experiencia
- Doble licencia inspirada en CockroachDB (BUSL-1.1 más AGPLv3)
